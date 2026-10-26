package dev.cs2telemetry.ui.minimap

import dev.cs2telemetry.data.model.RadarInfo
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class RadarProjectionTest {
    private val dust2 = RadarProjection.from(RadarInfo(posX = -2476f, posY = 3239f, scale = 4.4f, image = "de_dust2"))
    private val nuke = RadarProjection.from(RadarInfo(-3453f, 2887f, 7f, "de_nuke", splitZ = -495f, lowerImage = "de_nuke_lower"))

    @Test
    fun overviewOriginIsTheTopLeftPixel() {
        assertEquals(0f, dust2.radarX(-2476f), 0.001f)
        assertEquals(0f, dust2.radarY(3239f), 0.001f)
    }

    @Test
    fun worldNorthIsUpOnTheRadar() {
        val center = 512f * 4.4f
        assertEquals(512f, dust2.radarX(-2476f + center), 0.01f)
        assertEquals(512f, dust2.radarY(3239f - center), 0.01f)
        assertTrue(dust2.radarY(1000f) < dust2.radarY(0f)) // larger world Y = further north = smaller image Y
    }

    @Test
    fun unitsScaleWithTheMap() {
        assertEquals(144f / 4.4f, dust2.units(144f), 0.001f)
    }

    @Test
    fun multiLevelMapsSplitOnHeight() {
        assertTrue(nuke.hasLevels)
        assertEquals(MapLevel.UPPER, nuke.level(-400f))
        assertEquals(MapLevel.LOWER, nuke.level(-600f))
        assertFalse(dust2.hasLevels)
        assertEquals(MapLevel.UPPER, dust2.level(-10_000f))
    }
}
