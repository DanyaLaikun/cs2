package dev.cs2telemetry.data.net

import dev.cs2telemetry.data.model.GameMode
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.flow.filterNotNull
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import okhttp3.OkHttpClient
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class TelemetryClientTest {
    private val server = MockWebServer()
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)

    @After
    fun tearDown() {
        scope.cancel()
        server.shutdown()
    }

    private fun host(script: (WebSocket) -> Unit) = MockResponse().withWebSocketUpgrade(object : WebSocketListener() {
        override fun onOpen(webSocket: WebSocket, response: Response) = script(webSocket)
    })

    @Test
    fun streamsStateAndReconnectsWhenTheHostRestarts() = runBlocking {
        val fixture = javaClass.classLoader!!.getResource("state_spectator.json")!!.readText()
        server.enqueue(host { ws ->
            ws.send("""{"t":"hello","v":1,"server":"test-host","hb":2.0,"maxHz":30}""")
            ws.send(fixture)
            ws.close(1001, "host restarting")
        })
        server.enqueue(host { ws -> ws.send("""{"t":"hb","seq":7,"gsiAge":0.5,"clients":1}""") })
        server.start()

        val client = TelemetryClient(OkHttpClient(), scope)
        client.connect(Endpoint(server.hostName, server.port))

        val snapshot = withTimeout(5_000) { client.snapshot.filterNotNull().first() }
        assertEquals(GameMode.SPECTATOR, snapshot.state.mode)
        assertEquals(10, snapshot.state.players.size)

        // The first socket was closed by the host; the client must come back on its own.
        val health = withTimeout(5_000) { client.health.filterNotNull().first { it.gsiAgeSeconds == 0.5f } }
        assertEquals("test-host", health.server)
        assertEquals(2, server.requestCount)
        assertTrue(client.status.value is ConnectionStatus.Connected)

        client.disconnect()
        assertEquals(ConnectionStatus.Idle, client.status.value)
    }

    @Test
    fun unreachableHostReportsOfflineWithAReason() = runBlocking {
        val closed = MockWebServer().apply { start() }
        val port = closed.port
        closed.shutdown() // nothing listens there any more

        val client = TelemetryClient(OkHttpClient(), scope)
        client.connect(Endpoint("127.0.0.1", port))
        val offline = withTimeout(5_000) { client.status.first { it is ConnectionStatus.Offline } } as ConnectionStatus.Offline
        assertTrue(offline.reason, offline.reason.contains("adb reverse"))
        client.disconnect()
    }

    @Test
    fun endpointBuildsUrlsAndValidatesInput() {
        assertEquals("http://127.0.0.1:8090/ws", Endpoint().webSocketUrl().toString())
        assertEquals("http://10.0.0.2:9000/ws?token=a%20b", Endpoint("10.0.0.2", 9000, "a b").webSocketUrl().toString())
        assertEquals("http://127.0.0.1:8090/radar/de_nuke_lower.png", Endpoint().radarUrl("de_nuke_lower").toString())
        assertEquals(Endpoint("192.168.42.10", 8090, ""), Endpoint.parseOrNull(" 192.168.42.10 ", "8090", ""))
        assertEquals(null, Endpoint.parseOrNull("127.0.0.1", "70000", ""))
        assertEquals(null, Endpoint.parseOrNull("bad host!", "8090", ""))
        assertEquals(null, Endpoint.parseOrNull("127.0.0.1", "", ""))
    }

    @Test
    fun backoffIsShortAndCapped() {
        assertTrue(TelemetryClient.backoffMillis(1) in 250L..450L)
        assertTrue(TelemetryClient.backoffMillis(50) in 3_000L..3_200L)
    }
}
