package dev.cs2telemetry.ui.dashboard

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawing
import androidx.compose.foundation.layout.windowInsetsPadding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.LifecycleStartEffect
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import dev.cs2telemetry.data.model.GameMode
import dev.cs2telemetry.data.model.TelemetryState
import dev.cs2telemetry.data.model.Team
import dev.cs2telemetry.data.model.focusPlayer
import dev.cs2telemetry.data.model.teamPlayers
import dev.cs2telemetry.data.net.ConnectionStatus
import dev.cs2telemetry.data.net.Endpoint
import dev.cs2telemetry.data.net.HostHealth
import dev.cs2telemetry.data.net.Snapshot
import dev.cs2telemetry.ui.Format
import dev.cs2telemetry.ui.minimap.MinimapViewport
import dev.cs2telemetry.ui.minimap.RadarLayers
import dev.cs2telemetry.ui.minimap.TacticalMinimap
import dev.cs2telemetry.ui.theme.Palette
import dev.cs2telemetry.ui.theme.TelemetryTheme

@Composable
fun DashboardRoute(viewModel: DashboardViewModel = viewModel()) {
    // The link runs only while the dashboard is visible.
    LifecycleStartEffect(viewModel) {
        viewModel.onStart()
        onStopOrDispose { viewModel.onStop() }
    }
    val status by viewModel.status.collectAsStateWithLifecycle()
    val health by viewModel.health.collectAsStateWithLifecycle()
    val snapshot by viewModel.snapshot.collectAsStateWithLifecycle()
    val radar by viewModel.radar.collectAsStateWithLifecycle()
    val endpoint by viewModel.endpoint.collectAsStateWithLifecycle()

    DashboardScreen(
        status = status,
        health = health,
        snapshot = snapshot,
        radar = radar,
        endpoint = endpoint,
        onEndpointChange = viewModel::updateEndpoint,
    )
}

@Composable
fun DashboardScreen(
    status: ConnectionStatus,
    health: HostHealth?,
    snapshot: Snapshot?,
    radar: RadarLayers,
    endpoint: Endpoint,
    onEndpointChange: (Endpoint) -> Unit,
) {
    var showSettings by rememberSaveable { mutableStateOf(false) }
    val viewport = remember { MinimapViewport() }

    Surface(Modifier.fillMaxSize(), color = Palette.Background) {
        BoxWithConstraints(
            Modifier
                .fillMaxSize()
                .windowInsetsPadding(WindowInsets.safeDrawing)
                .padding(8.dp),
        ) {
            if (maxWidth > maxHeight) {
                // Landscape (tablet on a stand, phone on its side): square map left, details right.
                Row(Modifier.fillMaxSize(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    MinimapPanel(snapshot, radar, viewport, Modifier.fillMaxHeight().aspectRatio(1f, matchHeightConstraintsFirst = true))
                    Column(Modifier.weight(1f).fillMaxHeight(), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                        LinkBar(status, health, endpoint, onOpenSettings = { showSettings = true })
                        InfoColumn(snapshot?.state, Modifier.weight(1f))
                    }
                }
            } else {
                Column(Modifier.fillMaxSize(), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    LinkBar(status, health, endpoint, onOpenSettings = { showSettings = true })
                    MinimapPanel(snapshot, radar, viewport, Modifier.fillMaxWidth().aspectRatio(1f))
                    InfoColumn(snapshot?.state, Modifier.weight(1f))
                }
            }
        }
    }

    if (showSettings) {
        EndpointDialog(
            current = endpoint,
            onDismiss = { showSettings = false },
            onSave = {
                onEndpointChange(it)
                showSettings = false
            },
        )
    }
}

@Composable
private fun InfoColumn(state: TelemetryState?, modifier: Modifier) {
    Column(modifier.verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        if (state == null) {
            Panel {
                Text("Waiting for telemetry", style = MaterialTheme.typography.titleSmall, color = Palette.Text)
                Text(
                    "Start the host on the PC, run `adb reverse tcp:8090 tcp:8090`, and launch CS2 with the GSI cfg installed.",
                    style = MaterialTheme.typography.bodySmall,
                    color = Palette.TextMuted,
                )
            }
            return@Column
        }
        ScoreHeader(state.map, state.round, state.phase, state.bomb)
        ModeBanner(state.mode)
        state.map?.history?.takeIf { it.isNotEmpty() }?.let { RoundHistoryStrip(it) }
        state.focusPlayer?.let { FocusPlayerCard(it, state.mode) }
        if (state.mode == GameMode.SPECTATOR) {
            val ct = state.teamPlayers(Team.CT)
            val t = state.teamPlayers(Team.T)
            EconomyRow(ct, t, state.map?.ct, state.map?.t)
            TeamRoster(Team.CT, ct, state.focus, state.bomb?.carrier)
            TeamRoster(Team.T, t, state.focus, state.bomb?.carrier)
        }
    }
}

@Composable
private fun MinimapPanel(snapshot: Snapshot?, radar: RadarLayers, viewport: MinimapViewport, modifier: Modifier) {
    val state = snapshot?.state
    val radarInfo = state?.map?.radar
    Box(modifier.clip(RoundedCornerShape(10.dp)).background(Palette.Surface)) {
        TacticalMinimap(snapshot, radar, viewport, Modifier.fillMaxSize())

        Row(Modifier.align(Alignment.TopStart).padding(8.dp), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            OverlayChip(Format.upper(state?.map?.name?.takeIf { it.isNotEmpty() } ?: "no map"))
            if (radarInfo?.splitZ != null) OverlayChip(viewport.levelMode.label, onClick = viewport::cycleLevel)
        }
        Row(Modifier.align(Alignment.TopEnd).padding(8.dp), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            OverlayChip("FOLLOW", active = viewport.follow, onClick = viewport::toggleFollow)
            OverlayChip("RESET", onClick = viewport::reset)
        }
        if (radarInfo != null && radar.upper == null) {
            OverlayChip(
                "No radar image for ${radarInfo.image}: see pc-host/radars",
                Modifier.align(Alignment.BottomStart).padding(8.dp),
            )
        }
        minimapHint(state)?.let { hint ->
            Text(
                hint,
                Modifier.align(Alignment.Center).padding(24.dp),
                textAlign = TextAlign.Center,
                style = MaterialTheme.typography.bodyMedium,
                color = Palette.TextMuted,
            )
        }
    }
}

private fun minimapHint(state: TelemetryState?): String? = when {
    state == null -> "Waiting for telemetry…"
    state.mode == GameMode.MENU -> "In menus"
    state.map?.radar == null -> "No radar calibration for ${state.map?.name}. Add it to pc-host/maps.json"
    state.players.none { it.pos != null } -> "This feed carries no positions"
    else -> null
}

@Composable
private fun OverlayChip(
    text: String,
    modifier: Modifier = Modifier,
    active: Boolean = false,
    onClick: (() -> Unit)? = null,
) {
    val shape = RoundedCornerShape(6.dp)
    var chip = modifier
        .clip(shape)
        .background(if (active) Palette.CT.copy(alpha = 0.35f) else Color.Black.copy(alpha = 0.55f))
    if (onClick != null) chip = chip.clickable(onClick = onClick)
    Text(
        text,
        chip.padding(horizontal = 10.dp, vertical = 6.dp),
        style = MaterialTheme.typography.labelSmall,
        color = Palette.Text,
    )
}

@Composable
private fun EndpointDialog(current: Endpoint, onDismiss: () -> Unit, onSave: (Endpoint) -> Unit) {
    var host by rememberSaveable { mutableStateOf(current.host) }
    var port by rememberSaveable { mutableStateOf(current.port.toString()) }
    var token by rememberSaveable { mutableStateOf(current.token) }
    val parsed = Endpoint.parseOrNull(host, port, token)

    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Host link") },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text(
                    "USB with adb reverse: 127.0.0.1 port 8090.\nUSB tethering or Wi-Fi: the PC's IP address (host started with --bridge-host 0.0.0.0).",
                    style = MaterialTheme.typography.bodySmall,
                    color = Palette.TextMuted,
                )
                OutlinedTextField(host, { host = it }, label = { Text("Host") }, singleLine = true, isError = parsed == null)
                OutlinedTextField(
                    port,
                    { port = it.filter(Char::isDigit).take(5) },
                    label = { Text("Port") },
                    singleLine = true,
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                )
                OutlinedTextField(token, { token = it }, label = { Text("Bridge token (optional)") }, singleLine = true)
            }
        },
        confirmButton = {
            TextButton(onClick = { parsed?.let(onSave) }, enabled = parsed != null) { Text("Connect") }
        },
        dismissButton = {
            Row {
                TextButton(onClick = {
                    host = Endpoint.DEFAULT_HOST
                    port = Endpoint.DEFAULT_PORT.toString()
                    token = ""
                }) { Text("USB defaults") }
                TextButton(onClick = onDismiss) { Text("Cancel") }
            }
        },
    )
}

@Preview(widthDp = 900, heightDp = 480)
@Composable
private fun DashboardPreview() {
    TelemetryTheme {
        DashboardScreen(
            status = ConnectionStatus.Connected(Endpoint(), 0L),
            health = HostHealth(server = "preview", gsiAgeSeconds = 0.1f),
            snapshot = Snapshot(1, PreviewData.state, 0L),
            radar = RadarLayers.None,
            endpoint = Endpoint(),
            onEndpointChange = {},
        )
    }
}
