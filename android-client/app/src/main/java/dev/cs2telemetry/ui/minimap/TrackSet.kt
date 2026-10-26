package dev.cs2telemetry.ui.minimap

/** Reusable output of [TrackSet.sample], so the per-frame draw path allocates nothing. */
class TrackSample {
    var x = 0f
    var y = 0f
    var z = 0f
    var yaw = 0f
}

/**
 * Smooths keyed positions between host updates.
 *
 * GSI delivers 10-30 updates per second while the display refreshes at 60-120 Hz. Each new target is
 * approached from wherever the marker is *currently drawn*, over the measured update interval, so
 * motion stays continuous with about one update of latency. Large jumps (respawns, round resets)
 * snap instead of sliding across the map. Not thread-safe: use from the main thread.
 */
class TrackSet(
    private val teleportDistance: Float = 600f,
    private val minIntervalNanos: Long = 15_000_000L,
    private val maxIntervalNanos: Long = 250_000_000L,
) {
    private class Track {
        var fromX = 0f; var fromY = 0f; var fromZ = 0f; var fromYaw = 0f
        var toX = 0f; var toY = 0f; var toZ = 0f; var toYaw = 0f
        var startNanos = 0L
        var durationNanos = 0L
        var generation = 0

        fun snap(x: Float, y: Float, z: Float, yaw: Float, now: Long) {
            fromX = x; fromY = y; fromZ = z; fromYaw = yaw
            toX = x; toY = y; toZ = z; toYaw = yaw
            startNanos = now
            durationNanos = 0L
        }
    }

    private val tracks = HashMap<String, Track>()
    private val scratch = TrackSample()
    private var generation = 0
    private var updateNanos = 0L
    private var lastUpdateNanos = 0L

    /** Smoothed time between host updates. */
    var intervalNanos = 100_000_000L
        private set

    val size: Int get() = tracks.size

    /** Start applying one host update received at [now]. */
    fun begin(now: Long) {
        if (lastUpdateNanos != 0L) {
            val measured = now - lastUpdateNanos
            if (measured in 1..PAUSE_NANOS) {
                intervalNanos = ((intervalNanos * 3 + measured) / 4).coerceIn(minIntervalNanos, maxIntervalNanos)
            }
        }
        lastUpdateNanos = now
        updateNanos = now
        generation++
    }

    fun put(id: String, x: Float, y: Float, z: Float, yaw: Float) {
        val now = updateNanos
        val track = tracks[id]
        if (track == null) {
            tracks[id] = Track().also { it.snap(x, y, z, yaw, now); it.generation = generation }
            return
        }
        track.generation = generation
        sampleInto(track, now, scratch)
        val dx = x - scratch.x
        val dy = y - scratch.y
        if (dx * dx + dy * dy > teleportDistance * teleportDistance) {
            track.snap(x, y, z, yaw, now)
            return
        }
        track.fromX = scratch.x; track.fromY = scratch.y; track.fromZ = scratch.z; track.fromYaw = scratch.yaw
        track.toX = x; track.toY = y; track.toZ = z; track.toYaw = yaw
        track.startNanos = now
        track.durationNanos = intervalNanos
    }

    /** Finish the update: ids not seen in it are dropped. */
    fun end() {
        val iterator = tracks.values.iterator()
        while (iterator.hasNext()) {
            if (iterator.next().generation != generation) iterator.remove()
        }
    }

    fun sample(id: String, now: Long, out: TrackSample): Boolean {
        val track = tracks[id] ?: return false
        sampleInto(track, now, out)
        return true
    }

    fun isAnimating(now: Long): Boolean {
        for (track in tracks.values) {
            if (track.durationNanos > 0 && now < track.startNanos + track.durationNanos) return true
        }
        return false
    }

    private fun sampleInto(t: Track, now: Long, out: TrackSample) {
        val a = if (t.durationNanos <= 0L) 1f else ((now - t.startNanos).toFloat() / t.durationNanos).coerceIn(0f, 1f)
        out.x = t.fromX + (t.toX - t.fromX) * a
        out.y = t.fromY + (t.toY - t.fromY) * a
        out.z = t.fromZ + (t.toZ - t.fromZ) * a
        out.yaw = t.fromYaw + shortestTurn(t.fromYaw, t.toYaw) * a
    }

    companion object {
        private const val PAUSE_NANOS = 1_000_000_000L

        /** Signed angle in degrees from [from] to [to] the short way round, in [-180, 180]. */
        fun shortestTurn(from: Float, to: Float): Float {
            var d = (to - from) % 360f
            if (d > 180f) d -= 360f else if (d < -180f) d += 360f
            return d
        }
    }
}
