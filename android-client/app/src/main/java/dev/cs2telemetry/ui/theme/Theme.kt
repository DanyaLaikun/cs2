package dev.cs2telemetry.ui.theme

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import dev.cs2telemetry.data.model.Team

object Palette {
    val Background = Color(0xFF0B0F14)
    val Surface = Color(0xFF131A22)
    val SurfaceHigh = Color(0xFF1B2430)
    val Outline = Color(0xFF2A3644)
    val Text = Color(0xFFE6EDF3)
    val TextMuted = Color(0xFF8B98A5)
    val Ink = Color(0xFF0B0F14)
    val CT = Color(0xFF5DA9E9)
    val T = Color(0xFFE8B04B)
    val Good = Color(0xFF4CC38A)
    val Warn = Color(0xFFF5A524)
    val Danger = Color(0xFFF2545B)
    val Smoke = Color(0xFFB8C2CC)
    val Fire = Color(0xFFFF7A2F)
    val RadarBackdrop = Color(0xFF06090D)
    val RadarGrid = Color(0xFF16202B)
}

fun teamColor(team: Team?): Color = when (team) {
    Team.CT -> Palette.CT
    Team.T -> Palette.T
    null -> Palette.TextMuted
}

fun hpColor(hp: Int): Color = when {
    hp > 50 -> Palette.Good
    hp > 20 -> Palette.Warn
    else -> Palette.Danger
}

@Composable
fun TelemetryTheme(content: @Composable () -> Unit) {
    MaterialTheme(
        colorScheme = darkColorScheme(
            primary = Palette.CT,
            onPrimary = Palette.Ink,
            secondary = Palette.T,
            onSecondary = Palette.Ink,
            background = Palette.Background,
            onBackground = Palette.Text,
            surface = Palette.Surface,
            onSurface = Palette.Text,
            surfaceVariant = Palette.SurfaceHigh,
            onSurfaceVariant = Palette.TextMuted,
            surfaceContainerHigh = Palette.SurfaceHigh,
            outline = Palette.Outline,
            error = Palette.Danger,
        ),
        content = content,
    )
}
