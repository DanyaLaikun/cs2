package dev.cs2telemetry.ui.minimap

import dev.cs2telemetry.data.model.RadarInfo

enum class MapLevel { UPPER, LOWER }

/**
 * Maps game world coordinates onto the map's 1024x1024 radar image, using the calibration from the
 * game's overview file. World Y points north while image Y points down, hence the flip.
 */
class RadarProjection(
    private val posX: Float,
    private val posY: Float,
    private val scale: Float,
    private val splitZ: Float?,
) {
    fun radarX(worldX: Float): Float = (worldX - posX) / scale
    fun radarY(worldY: Float): Float = (posY - worldY) / scale
    fun units(worldUnits: Float): Float = worldUnits / scale

    /** Which radar layer a height belongs to; maps without a split are a single UPPER layer. */
    fun level(worldZ: Float): MapLevel =
        if (splitZ != null && worldZ < splitZ) MapLevel.LOWER else MapLevel.UPPER

    val hasLevels: Boolean get() = splitZ != null

    companion object {
        const val RADAR_SIZE = 1024f

        fun from(info: RadarInfo) = RadarProjection(info.posX, info.posY, info.scale, info.splitZ)
    }
}
