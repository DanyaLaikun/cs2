package dev.cs2telemetry.ui.minimap

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.gestures.detectTransformGestures
import androidx.compose.runtime.Composable
import androidx.compose.runtime.Immutable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.runtime.withFrameNanos
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.FilterQuality
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.TextLayoutResult
import androidx.compose.ui.text.TextMeasurer
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.drawText
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.rememberTextMeasurer
import androidx.compose.ui.unit.Density
import androidx.compose.ui.unit.IntOffset
import androidx.compose.ui.unit.IntSize
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.unit.toSize
import dev.cs2telemetry.data.model.BombInfo
import dev.cs2telemetry.data.model.Grenade
import dev.cs2telemetry.data.model.Player
import dev.cs2telemetry.data.model.RadarInfo
import dev.cs2telemetry.data.model.TelemetryState
import dev.cs2telemetry.data.model.focusPlayer
import dev.cs2telemetry.data.net.Snapshot
import dev.cs2telemetry.ui.theme.Palette
import dev.cs2telemetry.ui.theme.teamColor
import kotlin.math.cos
import kotlin.math.max
import kotlin.math.roundToInt
import kotlin.math.sin

/** Radar images for the current map; the lower layer exists only on multi-level maps. */
@Immutable
data class RadarLayers(val image: String? = null, val upper: ImageBitmap? = null, val lower: ImageBitmap? = null) {
    fun forLevel(level: MapLevel): ImageBitmap? = if (level == MapLevel.LOWER) lower ?: upper else upper

    companion object {
        val None = RadarLayers()
    }
}

/**
 * Hardware-accelerated tactical minimap.
 *
 * Rendering is driven by a frame clock rather than by recomposition: `frameNanos` is read only
 * inside the draw lambda, so each vsync re-runs the draw phase alone (no composition or layout).
 * The clock stops while nothing moves and resumes on the next snapshot.
 */
@Composable
fun TacticalMinimap(
    snapshot: Snapshot?,
    radar: RadarLayers,
    viewport: MinimapViewport,
    modifier: Modifier = Modifier,
) {
    val animator = remember { MinimapAnimator() }
    val textMeasurer = rememberTextMeasurer()
    val density = LocalDensity.current
    val resources = remember(textMeasurer, density) { MinimapResources(textMeasurer, density) }
    var frameNanos by remember { mutableLongStateOf(0L) }

    LaunchedEffect(snapshot) {
        snapshot?.let(animator::ingest)
    }
    LaunchedEffect(animator) {
        while (true) {
            withFrameNanos { frameNanos = it }
            if (!animator.needsFrames(frameNanos)) animator.awaitActivity()
        }
    }

    Canvas(
        modifier
            .pointerInput(viewport) {
                detectTransformGestures { centroid, pan, zoom, _ ->
                    viewport.applyGesture(size.toSize(), centroid, pan, zoom)
                }
            }
            .pointerInput(viewport) {
                detectTapGestures(onDoubleTap = { viewport.reset() })
            },
    ) {
        drawTacticalMap(snapshot?.state, radar, animator, viewport, frameNanos, resources)
    }
}

/** Objects reused every frame so drawing allocates nothing. */
internal class MinimapResources(textMeasurer: TextMeasurer, density: Density) {
    val sample = TrackSample()
    val view = ViewTransform()
    val cone = Path()

    val dotRadius = with(density) { 7.dp.toPx() }
    val outline = with(density) { 2.dp.toPx() }
    val coneLength = with(density) { 30.dp.toPx() }
    val focusGap = with(density) { 4.dp.toPx() }
    val crossWidth = with(density) { 2.5.dp.toPx() }
    val projectileRadius = with(density) { 3.dp.toPx() }
    val bombSize = with(density) { 9.dp.toPx() }
    val badgeSize = with(density) { 5.dp.toPx() }
    val minFlameRadius = with(density) { 3.dp.toPx() }
    val focusStroke = Stroke(width = with(density) { 2.dp.toPx() })
    val hpStroke = Stroke(width = with(density) { 2.dp.toPx() }, cap = StrokeCap.Butt)
    val thinStroke = Stroke(width = with(density) { 1.5.dp.toPx() })

    /** Pre-measured observer slot digits 0-9 drawn inside player markers. */
    val digits: Array<TextLayoutResult> = Array(10) {
        textMeasurer.measure(AnnotatedString(it.toString()), TextStyle(fontSize = 9.sp, fontWeight = FontWeight.Bold))
    }

    private var projectionKey: RadarInfo? = null
    private var projection: RadarProjection? = null

    fun projection(info: RadarInfo): RadarProjection {
        val cached = projection
        if (cached != null && info == projectionKey) return cached
        return RadarProjection.from(info).also {
            projection = it
            projectionKey = info
        }
    }
}

internal fun DrawScope.drawTacticalMap(
    state: TelemetryState?,
    radar: RadarLayers,
    animator: MinimapAnimator,
    viewport: MinimapViewport,
    nowNanos: Long,
    res: MinimapResources,
) {
    drawRect(Palette.RadarBackdrop)
    val info = state?.map?.radar
    if (state == null || info == null) {
        val extent = size.minDimension
        drawGrid(Offset((size.width - extent) / 2f, (size.height - extent) / 2f), extent)
        return
    }
    val projection = res.projection(info)
    val sample = res.sample

    // The focused player drives follow mode and the automatic level on multi-level maps.
    val focus = state.focusPlayer
    var focusX = Float.NaN
    var focusY = Float.NaN
    var focusZ = Float.NaN
    if (focus != null && focus.alive && animator.samplePlayer(focus.id, nowNanos, sample)) {
        focusX = projection.radarX(sample.x)
        focusY = projection.radarY(sample.y)
        focusZ = sample.z
    }
    val level = viewport.resolveLevel(projection, focusZ)
    val view = res.view
    viewport.layout(size, focusX, focusY, view)

    val mapExtent = RadarProjection.RADAR_SIZE * view.scale
    val image = radar.forLevel(level)
    if (image != null) {
        drawImage(
            image = image,
            dstOffset = IntOffset(view.originX.roundToInt(), view.originY.roundToInt()),
            dstSize = IntSize(mapExtent.roundToInt(), mapExtent.roundToInt()),
            filterQuality = FilterQuality.Medium,
        )
    } else {
        drawGrid(Offset(view.originX, view.originY), mapExtent)
    }

    for (grenade in state.grenades) drawGrenade(grenade, projection, view, animator, nowNanos, res)
    state.bomb?.let { drawBomb(it, projection, view, nowNanos, res) }

    // Dead underneath, then the living, the focused player last so it is never hidden.
    val carrier = state.bomb?.carrier
    for (p in state.players) {
        if (!p.alive) drawDeadPlayer(p, projection, view, level, animator, nowNanos, res)
    }
    for (p in state.players) {
        if (p.alive && p.id != state.focus) {
            drawPlayer(p, focused = false, hasBomb = p.id == carrier || p.hasBomb, projection, view, level, animator, nowNanos, res)
        }
    }
    if (focus != null && focus.alive) {
        drawPlayer(focus, focused = true, hasBomb = focus.id == carrier || focus.hasBomb, projection, view, level, animator, nowNanos, res)
    }
}

private fun DrawScope.drawGrid(topLeft: Offset, extent: Float) {
    drawRect(Palette.RadarGrid, topLeft, Size(extent, extent), alpha = 0.35f)
    val step = extent / GRID_CELLS
    for (i in 0..GRID_CELLS) {
        val d = i * step
        drawLine(Palette.RadarGrid, Offset(topLeft.x + d, topLeft.y), Offset(topLeft.x + d, topLeft.y + extent), strokeWidth = 1f)
        drawLine(Palette.RadarGrid, Offset(topLeft.x, topLeft.y + d), Offset(topLeft.x + extent, topLeft.y + d), strokeWidth = 1f)
    }
}

private fun DrawScope.drawGrenade(
    grenade: Grenade,
    projection: RadarProjection,
    view: ViewTransform,
    animator: MinimapAnimator,
    now: Long,
    res: MinimapResources,
) {
    if (grenade.type == "inferno") {
        val radius = max(res.minFlameRadius, projection.units(FLAME_RADIUS_UNITS) * view.scale)
        for (flame in grenade.flames) {
            if (flame.size < 2) continue
            val center = Offset(view.x(projection.radarX(flame[0])), view.y(projection.radarY(flame[1])))
            drawCircle(Palette.Fire, radius, center, alpha = 0.45f)
        }
        return
    }
    val s = res.sample
    if (!animator.sampleGrenade(grenade.id, now, s)) return
    val center = Offset(view.x(projection.radarX(s.x)), view.y(projection.radarY(s.y)))
    if (grenade.type == "smoke" && (grenade.effect ?: 0f) > 0f) {
        val radius = projection.units(SMOKE_RADIUS_UNITS) * view.scale
        drawCircle(Palette.Smoke, radius, center, alpha = 0.45f)
        drawCircle(Palette.Smoke, radius, center, alpha = 0.8f, style = res.thinStroke)
        return
    }
    val color = when (grenade.type) {
        "frag" -> Palette.Danger
        "flashbang" -> Color.White
        "firebomb" -> Palette.Fire
        "smoke" -> Palette.Smoke
        else -> Palette.TextMuted
    }
    drawCircle(Palette.Ink, res.projectileRadius + res.outline, center)
    drawCircle(color, res.projectileRadius, center)
}

private fun DrawScope.drawBomb(
    bomb: BombInfo,
    projection: RadarProjection,
    view: ViewTransform,
    now: Long,
    res: MinimapResources,
) {
    val pos = bomb.pos ?: return
    if (pos.size < 2 || bomb.state == "carried") return // carried: shown as a badge on the carrier
    val center = Offset(view.x(projection.radarX(pos[0])), view.y(projection.radarY(pos[1])))
    val color = when (bomb.state) {
        "defused" -> Palette.CT
        "dropped" -> Palette.Warn
        else -> Palette.Danger
    }
    if (bomb.state == "planted" || bomb.state == "defusing") {
        val phase = (now / 1_000_000L % PULSE_MILLIS).toFloat() / PULSE_MILLIS
        drawCircle(color, res.bombSize * (0.8f + 2.2f * phase), center, alpha = 0.7f * (1f - phase), style = res.thinStroke)
    }
    val half = res.bombSize / 2f
    val o = res.outline
    drawRect(Palette.Ink, Offset(center.x - half - o, center.y - half - o), Size(res.bombSize + 2 * o, res.bombSize + 2 * o))
    drawRect(color, Offset(center.x - half, center.y - half), Size(res.bombSize, res.bombSize))
}

private fun DrawScope.drawPlayer(
    p: Player,
    focused: Boolean,
    hasBomb: Boolean,
    projection: RadarProjection,
    view: ViewTransform,
    level: MapLevel,
    animator: MinimapAnimator,
    now: Long,
    res: MinimapResources,
) {
    val s = res.sample
    if (!animator.samplePlayer(p.id, now, s)) return
    val cx = view.x(projection.radarX(s.x))
    val cy = view.y(projection.radarY(s.y))
    val center = Offset(cx, cy)
    val alpha = if (projection.level(s.z) == level) 1f else OTHER_LEVEL_ALPHA
    val color = teamColor(p.team)
    val r = res.dotRadius

    if (p.yaw != null) {
        // World yaw is counter-clockwise from +X; screen angles run clockwise because Y points down.
        buildCone(res.cone, cx, cy, -s.yaw, res.coneLength)
        drawPath(res.cone, color, alpha = 0.28f * alpha)
    }
    drawCircle(Palette.Ink, r + res.outline, center, alpha = alpha)
    drawCircle(color, r, center, alpha = alpha)
    if (p.hp < 100) {
        // Missing health as a red arc on the marker's rim.
        val missing = 360f * (100 - p.hp.coerceIn(0, 100)) / 100f
        val ring = r + res.outline / 2f
        drawArc(
            color = Palette.Danger,
            startAngle = -90f - missing,
            sweepAngle = missing,
            useCenter = false,
            topLeft = Offset(cx - ring, cy - ring),
            size = Size(ring * 2, ring * 2),
            alpha = alpha,
            style = res.hpStroke,
        )
    }
    if (p.flashed > 0) drawCircle(Color.White, r * 0.85f, center, alpha = alpha * p.flashed / 255f)
    p.slot?.let { slot ->
        val digit = res.digits[((slot % 10) + 10) % 10]
        drawText(
            digit,
            color = Palette.Ink,
            topLeft = Offset(cx - digit.size.width / 2f, cy - digit.size.height / 2f),
            alpha = alpha,
        )
    }
    if (focused) drawCircle(Color.White, r + res.focusGap, center, style = res.focusStroke)
    if (hasBomb) {
        val b = res.badgeSize
        drawRect(Palette.Danger, Offset(cx + r * 0.4f, cy - r - b * 0.7f), Size(b, b), alpha = alpha)
    }
}

private fun DrawScope.drawDeadPlayer(
    p: Player,
    projection: RadarProjection,
    view: ViewTransform,
    level: MapLevel,
    animator: MinimapAnimator,
    now: Long,
    res: MinimapResources,
) {
    val s = res.sample
    if (!animator.samplePlayer(p.id, now, s)) return
    val cx = view.x(projection.radarX(s.x))
    val cy = view.y(projection.radarY(s.y))
    val alpha = 0.55f * if (projection.level(s.z) == level) 1f else OTHER_LEVEL_ALPHA
    val d = res.dotRadius * 0.7f
    val color = teamColor(p.team)
    drawLine(color, Offset(cx - d, cy - d), Offset(cx + d, cy + d), strokeWidth = res.crossWidth, alpha = alpha)
    drawLine(color, Offset(cx + d, cy - d), Offset(cx - d, cy + d), strokeWidth = res.crossWidth, alpha = alpha)
}

private fun buildCone(path: Path, cx: Float, cy: Float, screenAngleDeg: Float, length: Float) {
    path.reset()
    path.moveTo(cx, cy)
    val start = Math.toRadians((screenAngleDeg - CONE_HALF_ANGLE).toDouble())
    val step = Math.toRadians((2 * CONE_HALF_ANGLE / CONE_SEGMENTS).toDouble())
    for (i in 0..CONE_SEGMENTS) {
        val a = start + step * i
        path.lineTo(cx + length * cos(a).toFloat(), cy + length * sin(a).toFloat())
    }
    path.close()
}

private const val GRID_CELLS = 16
private const val SMOKE_RADIUS_UNITS = 144f
private const val FLAME_RADIUS_UNITS = 48f
private const val CONE_HALF_ANGLE = 40f
private const val CONE_SEGMENTS = 6
private const val OTHER_LEVEL_ALPHA = 0.3f
private const val PULSE_MILLIS = 1_000L
