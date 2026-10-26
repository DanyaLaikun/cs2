package dev.cs2telemetry.data.net

import androidx.compose.runtime.Immutable
import dev.cs2telemetry.data.model.TelemetryState

/** One state frame plus its arrival time (System.nanoTime), which the minimap interpolates against. */
@Immutable
data class Snapshot(val seq: Long, val state: TelemetryState, val receivedAtNanos: Long)

/** What the host's heartbeat says about the game side of the pipeline. */
@Immutable
data class HostHealth(
    val server: String = "",
    /** Seconds since CS2 last posted to the host; null if it never has since the host started. */
    val gsiAgeSeconds: Float? = null,
    val clients: Int = 0,
    val receivedAtNanos: Long = 0,
)

sealed interface ConnectionStatus {
    data object Idle : ConnectionStatus
    data class Connecting(val endpoint: Endpoint, val attempt: Int) : ConnectionStatus
    data class Connected(val endpoint: Endpoint, val sinceNanos: Long) : ConnectionStatus
    data class Offline(val endpoint: Endpoint, val reason: String, val retryInMillis: Long) : ConnectionStatus
}
