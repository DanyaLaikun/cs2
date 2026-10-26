package dev.cs2telemetry.ui.minimap

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class TrackSetTest {
    private val ms = 1_000_000L
    private val out = TrackSample()

    private fun TrackSet.update(now: Long, vararg points: Triple<String, Float, Float>) {
        begin(now)
        for ((id, x, y) in points) put(id, x, y, 0f, 0f)
        end()
    }

    @Test
    fun firstSightingSnapsThenInterpolatesOverTheUpdateInterval() {
        val tracks = TrackSet()
        tracks.update(1_000 * ms, Triple("a", 0f, 0f))
        assertTrue(tracks.sample("a", 1_000 * ms, out))
        assertEquals(0f, out.x, 0.001f)

        tracks.update(1_100 * ms, Triple("a", 100f, 0f)) // 100 ms later: matches the default interval
        tracks.sample("a", 1_150 * ms, out)
        assertEquals(50f, out.x, 0.5f)
        tracks.sample("a", 1_200 * ms, out)
        assertEquals(100f, out.x, 0.001f)
        assertFalse(tracks.isAnimating(1_200 * ms))
    }

    @Test
    fun retargetingStartsFromTheCurrentlyDrawnPosition() {
        val tracks = TrackSet()
        tracks.update(0, Triple("a", 0f, 0f))
        tracks.update(100 * ms, Triple("a", 100f, 0f))
        tracks.update(150 * ms, Triple("a", 100f, 100f)) // arrives mid-way: no jump backwards or forwards
        tracks.sample("a", 150 * ms, out)
        assertTrue("x=${out.x}", out.x in 40f..60f)
        assertEquals(0f, out.y, 0.5f)
    }

    @Test
    fun teleportsSnapInsteadOfSliding() {
        val tracks = TrackSet(teleportDistance = 600f)
        tracks.update(0, Triple("a", 0f, 0f))
        tracks.update(100 * ms, Triple("a", 5_000f, 0f))
        tracks.sample("a", 100 * ms, out)
        assertEquals(5_000f, out.x, 0.001f)
    }

    @Test
    fun idsMissingFromAnUpdateAreDropped() {
        val tracks = TrackSet()
        tracks.update(0, Triple("a", 0f, 0f), Triple("b", 1f, 1f))
        tracks.update(100 * ms, Triple("b", 2f, 2f))
        assertFalse(tracks.sample("a", 100 * ms, out))
        assertEquals(1, tracks.size)
    }

    @Test
    fun intervalAdaptsToTheFeedRate() {
        val tracks = TrackSet()
        var now = 0L
        repeat(40) {
            tracks.update(now, Triple("a", it.toFloat(), 0f))
            now += 50 * ms
        }
        assertEquals(50 * ms.toDouble(), tracks.intervalNanos.toDouble(), 2.0 * ms)
    }

    @Test
    fun yawTurnsTheShortWay() {
        assertEquals(20f, TrackSet.shortestTurn(170f, -170f), 0.001f)
        assertEquals(-20f, TrackSet.shortestTurn(-170f, 170f), 0.001f)
        assertEquals(90f, TrackSet.shortestTurn(0f, 90f), 0.001f)
        assertEquals(-10f, TrackSet.shortestTurn(5f, 355f), 0.001f)
    }
}
