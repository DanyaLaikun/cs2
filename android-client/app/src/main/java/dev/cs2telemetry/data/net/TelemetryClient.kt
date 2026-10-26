package dev.cs2telemetry.data.net

import android.util.Log
import dev.cs2telemetry.data.model.HostMessage
import dev.cs2telemetry.data.model.PROTOCOL_VERSION
import dev.cs2telemetry.data.model.ProtocolJson
import java.io.EOFException
import java.net.ConnectException
import java.net.SocketTimeoutException
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicLong
import kotlin.coroutines.resume
import kotlin.random.Random
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.serialization.json.Json
import kotlinx.serialization.serializer
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener

/**
 * Keeps one WebSocket to the PC host alive and exposes what arrives as StateFlows.
 *
 * - Reconnects forever with short capped backoff: cables get replugged and the host restarts.
 * - OkHttp sends WebSocket pings; a missing pong fails the socket, so a dead USB tunnel is
 *   detected in seconds rather than at the next TCP timeout.
 * - Frames are decoded on OkHttp's reader thread; StateFlow hands the newest one to the UI
 *   (conflated: if rendering lags, intermediate states are simply skipped).
 */
class TelemetryClient(
    baseClient: OkHttpClient,
    private val scope: CoroutineScope,
    private val json: Json = ProtocolJson,
    pingIntervalMillis: Long = 3_000,
) {
    private val socketClient = baseClient.newBuilder()
        .readTimeout(0, TimeUnit.MILLISECONDS) // the stream may idle between heartbeats; pings cover liveness
        .pingInterval(pingIntervalMillis, TimeUnit.MILLISECONDS)
        .retryOnConnectionFailure(false)
        .build()

    private val _status = MutableStateFlow<ConnectionStatus>(ConnectionStatus.Idle)
    val status: StateFlow<ConnectionStatus> = _status.asStateFlow()

    private val _snapshot = MutableStateFlow<Snapshot?>(null)
    val snapshot: StateFlow<Snapshot?> = _snapshot.asStateFlow()

    private val _health = MutableStateFlow<HostHealth?>(null)
    val health: StateFlow<HostHealth?> = _health.asStateFlow()

    private val messageSerializer = serializer<HostMessage>()

    /** Bumped on every connect/disconnect so callbacks from an abandoned socket are ignored. */
    private val generation = AtomicLong()
    private var loop: Job? = null

    fun connect(endpoint: Endpoint) {
        val gen = generation.incrementAndGet()
        loop?.cancel()
        loop = scope.launch { connectionLoop(endpoint, gen) }
    }

    fun disconnect() {
        generation.incrementAndGet()
        loop?.cancel()
        loop = null
        _status.value = ConnectionStatus.Idle
    }

    private suspend fun connectionLoop(endpoint: Endpoint, gen: Long) {
        var failures = 0
        while (true) {
            _status.value = ConnectionStatus.Connecting(endpoint, failures)
            val session = runSession(endpoint, gen)
            failures = if (session.wasOpen) 1 else failures + 1
            val wait = backoffMillis(failures)
            if (isCurrent(gen)) _status.value = ConnectionStatus.Offline(endpoint, session.reason, wait)
            delay(wait)
        }
    }

    private class SessionEnd(val reason: String, val wasOpen: Boolean)

    /** Opens a socket and suspends until it closes or fails. Cancelling the caller cancels the socket. */
    private suspend fun runSession(endpoint: Endpoint, gen: Long): SessionEnd =
        suspendCancellableCoroutine { cont ->
            val opened = AtomicBoolean(false)
            val request = Request.Builder().url(endpoint.webSocketUrl()).build()
            val socket = socketClient.newWebSocket(request, object : WebSocketListener() {
                override fun onOpen(webSocket: WebSocket, response: Response) {
                    opened.set(true)
                    if (isCurrent(gen)) _status.value = ConnectionStatus.Connected(endpoint, System.nanoTime())
                }

                override fun onMessage(webSocket: WebSocket, text: String) {
                    if (isCurrent(gen)) handleMessage(text)
                }

                override fun onClosing(webSocket: WebSocket, code: Int, reason: String) {
                    webSocket.close(NORMAL_CLOSURE, null)
                }

                override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
                    val detail = if (reason.isNotEmpty()) "$code, $reason" else "$code"
                    if (cont.isActive) cont.resume(SessionEnd("Host closed the link ($detail)", opened.get()))
                }

                override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                    if (cont.isActive) cont.resume(SessionEnd(describeFailure(t, response), opened.get()))
                }
            })
            cont.invokeOnCancellation { socket.cancel() }
        }

    private fun handleMessage(text: String) {
        val message = try {
            json.decodeFromString(messageSerializer, text)
        } catch (e: IllegalArgumentException) { // includes SerializationException
            Log.w(TAG, "Ignoring unreadable message: ${e.message}")
            return
        }
        val now = System.nanoTime()
        when (message) {
            is HostMessage.State -> _snapshot.value = Snapshot(message.seq, message.d, now)
            is HostMessage.Heartbeat -> _health.value = (_health.value ?: HostHealth()).copy(
                gsiAgeSeconds = message.gsiAge,
                clients = message.clients,
                receivedAtNanos = now,
            )
            is HostMessage.Hello -> {
                _health.value = HostHealth(server = message.server, receivedAtNanos = now)
                if (message.v != PROTOCOL_VERSION) {
                    Log.w(TAG, "Host speaks protocol v${message.v}, app expects v$PROTOCOL_VERSION")
                }
            }
        }
    }

    private fun isCurrent(gen: Long) = generation.get() == gen

    companion object {
        private const val TAG = "TelemetryClient"
        private const val NORMAL_CLOSURE = 1000
        private const val INITIAL_BACKOFF_MS = 250L
        private const val MAX_BACKOFF_MS = 3_000L

        internal fun backoffMillis(failures: Int): Long {
            val exponential = INITIAL_BACKOFF_MS shl (failures - 1).coerceIn(0, 4)
            return exponential.coerceAtMost(MAX_BACKOFF_MS) + Random.nextLong(0, 200)
        }

        /** Turn transport errors into something a person at the PC can act on. */
        internal fun describeFailure(t: Throwable, response: Response?): String = when {
            response?.code == 401 -> "Host rejected the bridge token"
            response != null -> "Handshake rejected (HTTP ${response.code})"
            t is ConnectException -> "No route to host: is `adb reverse tcp:8090 tcp:8090` active?"
            t is EOFException || t.message?.contains("end of stream") == true ->
                "Tunnel is up but the host is not answering: is it running on the PC?"
            t is SocketTimeoutException -> "Link timed out"
            else -> t.message ?: t.javaClass.simpleName
        }
    }
}
