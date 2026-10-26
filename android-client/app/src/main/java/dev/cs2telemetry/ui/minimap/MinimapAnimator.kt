package dev.cs2telemetry.ui.minimap

import dev.cs2telemetry.data.net.Snapshot
import kotlinx.coroutines.channels.Channel

/**
 * Feeds snapshots into interpolation tracks and tells the frame loop when it may go idle, so the
 * minimap only redraws every vsync while something is actually moving or pulsing.
 */
class MinimapAnimator {
    private val players = TrackSet()
    private val grenades = TrackSet()
    private val wake = Channel<Unit>(Channel.CONFLATED)
    private var pulsing = false

    fun ingest(snapshot: Snapshot) {
        val state = snapshot.state
        players.begin(snapshot.receivedAtNanos)
        for (p in state.players) {
            val pos = p.pos ?: continue
            if (pos.size >= 3) players.put(p.id, pos[0], pos[1], pos[2], p.yaw ?: 0f)
        }
        players.end()

        grenades.begin(snapshot.receivedAtNanos)
        for (g in state.grenades) {
            val pos = g.pos ?: continue
            if (pos.size >= 3) grenades.put(g.id, pos[0], pos[1], pos[2], 0f)
        }
        grenades.end()

        pulsing = state.bomb?.state.let { it == "planted" || it == "defusing" }
        wake.trySend(Unit)
    }

    fun samplePlayer(id: String, now: Long, out: TrackSample): Boolean = players.sample(id, now, out)

    fun sampleGrenade(id: String, now: Long, out: TrackSample): Boolean = grenades.sample(id, now, out)

    fun needsFrames(now: Long): Boolean = pulsing || players.isAnimating(now) || grenades.isAnimating(now)

    /** Suspends the frame loop until the next snapshot arrives. */
    suspend fun awaitActivity() {
        wake.receive()
    }
}
