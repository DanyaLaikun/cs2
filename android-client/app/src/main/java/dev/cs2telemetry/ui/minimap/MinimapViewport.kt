package dev.cs2telemetry.ui.minimap

import androidx.compose.runtime.Stable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import dev.cs2telemetry.ui.minimap.RadarProjection.Companion.RADAR_SIZE
import kotlin.math.min

enum class LevelMode(val label: String) { AUTO("LEVEL: AUTO"), UPPER("LEVEL: UPPER"), LOWER("LEVEL: LOWER") }

/** Radar-space -> screen-space transform for one frame. Mutable and reused to avoid allocation. */
class ViewTransform {
    var scale = 1f
    var originX = 0f
    var originY = 0f

    fun x(radarX: Float): Float = originX + radarX * scale
    fun y(radarY: Float): Float = originY + radarY * scale
}

/**
 * Zoom, pan, follow and level selection for the minimap. Values are snapshot state read during the
 * draw phase, so changing them only invalidates drawing, not composition or layout.
 */
@Stable
class MinimapViewport {
    var zoom by mutableFloatStateOf(1f)
        private set
    var centerX by mutableFloatStateOf(RADAR_SIZE / 2)
        private set
    var centerY by mutableFloatStateOf(RADAR_SIZE / 2)
        private set
    var follow by mutableStateOf(false)
    var levelMode by mutableStateOf(LevelMode.AUTO)

    // Center actually used by the last frame (differs from centerX/Y while following). Plain fields:
    // written during draw, read by gestures, must not trigger invalidation.
    private var drawnCenterX = RADAR_SIZE / 2
    private var drawnCenterY = RADAR_SIZE / 2

    fun reset() {
        zoom = 1f
        centerX = RADAR_SIZE / 2
        centerY = RADAR_SIZE / 2
        follow = false
    }

    fun toggleFollow() {
        if (follow) {
            centerX = drawnCenterX
            centerY = drawnCenterY
        } else if (zoom < FOLLOW_MIN_ZOOM) {
            zoom = FOLLOW_MIN_ZOOM // following at 1x would not move anything
        }
        follow = !follow
    }

    fun cycleLevel() {
        levelMode = LevelMode.entries[(levelMode.ordinal + 1) % LevelMode.entries.size]
    }

    fun resolveLevel(projection: RadarProjection, focusZ: Float): MapLevel = when (levelMode) {
        LevelMode.UPPER -> MapLevel.UPPER
        LevelMode.LOWER -> MapLevel.LOWER
        LevelMode.AUTO -> if (focusZ.isNaN()) MapLevel.UPPER else projection.level(focusZ)
    }

    /** Compute this frame's transform; pass NaN follow coordinates to use the manual center. */
    fun layout(canvas: Size, followX: Float, followY: Float, out: ViewTransform) {
        val scale = min(canvas.width, canvas.height) / RADAR_SIZE * zoom
        val cx = if (follow && !followX.isNaN()) followX else centerX
        val cy = if (follow && !followY.isNaN()) followY else centerY
        drawnCenterX = cx
        drawnCenterY = cy
        out.scale = scale
        out.originX = canvas.width / 2f - cx * scale
        out.originY = canvas.height / 2f - cy * scale
    }

    /** Pinch-zoom around the fingers and pan; a deliberate pan ends follow mode. */
    fun applyGesture(canvas: Size, centroid: Offset, pan: Offset, zoomChange: Float) {
        val fit = min(canvas.width, canvas.height) / RADAR_SIZE
        if (fit <= 0f) return
        val oldScale = fit * zoom
        val newZoom = (zoom * zoomChange).coerceIn(MIN_ZOOM, MAX_ZOOM)
        val newScale = fit * newZoom
        if (follow && pan.getDistance() > PAN_BREAKS_FOLLOW_PX) {
            follow = false
        }
        zoom = newZoom
        if (follow) return // keep the followed player centered; only the zoom changes
        val anchorX = centroid.x - canvas.width / 2f
        val anchorY = centroid.y - canvas.height / 2f
        centerX = (drawnCenterX + anchorX / oldScale - anchorX / newScale - pan.x / newScale).coerceIn(0f, RADAR_SIZE)
        centerY = (drawnCenterY + anchorY / oldScale - anchorY / newScale - pan.y / newScale).coerceIn(0f, RADAR_SIZE)
        drawnCenterX = centerX
        drawnCenterY = centerY
    }

    private companion object {
        const val MIN_ZOOM = 1f
        const val MAX_ZOOM = 6f
        const val FOLLOW_MIN_ZOOM = 2f
        const val PAN_BREAKS_FOLLOW_PX = 12f
    }
}
