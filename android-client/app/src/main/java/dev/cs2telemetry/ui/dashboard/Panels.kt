package dev.cs2telemetry.ui.dashboard

import androidx.compose.foundation.background
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import dev.cs2telemetry.data.model.BombInfo
import dev.cs2telemetry.data.model.GameMode
import dev.cs2telemetry.data.model.MapInfo
import dev.cs2telemetry.data.model.PhaseInfo
import dev.cs2telemetry.data.model.Player
import dev.cs2telemetry.data.model.RoundInfo
import dev.cs2telemetry.data.model.RoundResult
import dev.cs2telemetry.data.model.Team
import dev.cs2telemetry.data.model.TeamInfo
import dev.cs2telemetry.data.model.Weapon
import dev.cs2telemetry.data.net.ConnectionStatus
import dev.cs2telemetry.data.net.Endpoint
import dev.cs2telemetry.data.net.HostHealth
import dev.cs2telemetry.ui.Economy
import dev.cs2telemetry.ui.Format
import dev.cs2telemetry.ui.theme.Palette
import dev.cs2telemetry.ui.theme.hpColor
import dev.cs2telemetry.ui.theme.teamColor

private val PanelShape = RoundedCornerShape(10.dp)

@Composable
fun Panel(modifier: Modifier = Modifier, content: @Composable ColumnScope.() -> Unit) {
    Surface(modifier = modifier.fillMaxWidth(), color = Palette.Surface, shape = PanelShape) {
        Column(Modifier.padding(12.dp), content = content)
    }
}

@Composable
private fun Caption(text: String, color: Color = Palette.TextMuted) {
    Text(text, style = MaterialTheme.typography.labelSmall, color = color, letterSpacing = 1.sp)
}

// --- link status ----------------------------------------------------------------------------------

@Composable
fun LinkBar(status: ConnectionStatus, health: HostHealth?, endpoint: Endpoint, onOpenSettings: () -> Unit) {
    val (color, label) = when (status) {
        is ConnectionStatus.Connected -> Palette.Good to "LINKED"
        is ConnectionStatus.Connecting -> Palette.Warn to "CONNECTING"
        is ConnectionStatus.Offline -> Palette.Danger to "OFFLINE"
        ConnectionStatus.Idle -> Palette.TextMuted to "PAUSED"
    }
    val detail = when (status) {
        is ConnectionStatus.Connected -> gameFeedLabel(health)
        is ConnectionStatus.Connecting -> "Reaching ${status.endpoint.label}…"
        is ConnectionStatus.Offline -> "${status.reason} · retry in ${(status.retryInMillis + 999) / 1000}s"
        ConnectionStatus.Idle -> "Link paused while the app is in the background"
    }
    Surface(color = Palette.Surface, shape = PanelShape, modifier = Modifier.fillMaxWidth()) {
        Row(Modifier.padding(start = 12.dp, end = 4.dp), verticalAlignment = Alignment.CenterVertically) {
            Box(Modifier.size(8.dp).background(color, CircleShape))
            Spacer(Modifier.width(8.dp))
            Text(label, style = MaterialTheme.typography.labelLarge, color = color, fontWeight = FontWeight.Bold)
            Spacer(Modifier.width(10.dp))
            Text(
                detail,
                style = MaterialTheme.typography.bodySmall,
                color = Palette.TextMuted,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
                modifier = Modifier.weight(1f),
            )
            TextButton(onClick = onOpenSettings) { Text(endpoint.label, style = MaterialTheme.typography.labelMedium) }
        }
    }
}

private fun gameFeedLabel(health: HostHealth?): String {
    val age = health?.gsiAgeSeconds
    return when {
        health == null -> "Host linked"
        age == null -> "Host linked · no game data yet (CS2 running with the GSI cfg?)"
        age > GAME_IDLE_SECONDS -> "Host linked · game feed idle for ${age.toInt()}s"
        else -> "Game feed live"
    }
}

private const val GAME_IDLE_SECONDS = 15f // GSI heartbeats every 10 s even when nothing changes

// --- match header ---------------------------------------------------------------------------------

@Composable
fun ScoreHeader(map: MapInfo?, round: RoundInfo?, phase: PhaseInfo?, bomb: BombInfo?) {
    Panel {
        Row(verticalAlignment = Alignment.CenterVertically) {
            TeamScore(map?.ct?.name ?: "CT", map?.ct?.score ?: 0, Palette.CT, Modifier.weight(1f), TextAlign.Start)
            Column(horizontalAlignment = Alignment.CenterHorizontally) {
                Caption(Format.upper(map?.name ?: "no map"))
                Text(
                    "ROUND ${(map?.round ?: 0) + 1}",
                    style = MaterialTheme.typography.titleSmall,
                    color = Palette.Text,
                    fontWeight = FontWeight.SemiBold,
                )
                val (label, color) = phaseLabel(round, phase, bomb)
                Text(label, style = MaterialTheme.typography.labelMedium, color = color)
            }
            TeamScore(map?.t?.name ?: "T", map?.t?.score ?: 0, Palette.T, Modifier.weight(1f), TextAlign.End)
        }
    }
}

@Composable
private fun TeamScore(name: String, score: Int, color: Color, modifier: Modifier, align: TextAlign) {
    Column(modifier, horizontalAlignment = if (align == TextAlign.End) Alignment.End else Alignment.Start) {
        Text("$score", fontSize = 32.sp, fontWeight = FontWeight.Bold, color = color)
        Text(name, style = MaterialTheme.typography.labelSmall, color = color, maxLines = 1, overflow = TextOverflow.Ellipsis)
    }
}

private fun phaseLabel(round: RoundInfo?, phase: PhaseInfo?, bomb: BombInfo?): Pair<String, Color> {
    val countdown = phase?.endsIn?.let { " " + Format.clock(it) }.orEmpty()
    val bombTimer = bomb?.countdown?.let { " " + Format.clock(it) }.orEmpty()
    val winner = round?.winTeam
    val phaseName = phase?.name
    return when {
        bomb?.state == "defusing" -> "DEFUSING$countdown" to Palette.CT
        bomb?.state == "planted" || round?.bomb == "planted" -> "BOMB PLANTED$bombTimer" to Palette.Danger
        winner != null -> "${winner.name} WIN" to teamColor(winner)
        phaseName != null -> Format.upper(phaseName) + countdown to Palette.TextMuted
        else -> Format.upper(round?.phase) to Palette.TextMuted
    }
}

@Composable
fun ModeBanner(mode: GameMode) {
    val text = when (mode) {
        GameMode.PLAYER ->
            "Live play feed: Valve's Game State Integration reports only your own player while you play. " +
                "Teammates, enemies, bomb and utility appear when you spectate, watch GOTV or a demo."
        GameMode.MENU -> "In menus: waiting for a match to load."
        GameMode.SPECTATOR -> return
    }
    Surface(color = Palette.SurfaceHigh, shape = PanelShape, modifier = Modifier.fillMaxWidth()) {
        Text(text, Modifier.padding(10.dp), style = MaterialTheme.typography.bodySmall, color = Palette.TextMuted)
    }
}

@Composable
fun RoundHistoryStrip(history: List<RoundResult>) {
    Panel {
        Caption("ROUNDS")
        Spacer(Modifier.height(6.dp))
        Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(3.dp)) {
            for (result in history) {
                Box(
                    Modifier.size(width = 18.dp, height = 22.dp).background(teamColor(result.w), RoundedCornerShape(3.dp)),
                    contentAlignment = Alignment.Center,
                ) {
                    Text(reasonGlyph(result.why), fontSize = 10.sp, fontWeight = FontWeight.Bold, color = Palette.Ink)
                }
            }
        }
    }
}

private fun reasonGlyph(why: String?): String = when (why) {
    "elimination" -> "E"
    "bomb" -> "B"
    "defuse" -> "D"
    "time" -> "T"
    "rescue" -> "R"
    else -> "·"
}

// --- focused player -------------------------------------------------------------------------------

@Composable
fun FocusPlayerCard(player: Player, mode: GameMode) {
    Panel {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Box(Modifier.size(width = 4.dp, height = 34.dp).background(teamColor(player.team), RoundedCornerShape(2.dp)))
            Spacer(Modifier.width(10.dp))
            Column(Modifier.weight(1f)) {
                Text(
                    player.name,
                    style = MaterialTheme.typography.titleMedium,
                    color = Palette.Text,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
                Caption(if (mode == GameMode.SPECTATOR) "OBSERVED PLAYER" else "YOU")
            }
            Text(Format.money(player.money), style = MaterialTheme.typography.titleMedium, color = Palette.Good)
        }
        Spacer(Modifier.height(10.dp))
        StatBar("HP", player.hp, hpColor(player.hp), suffix = if (player.alive) null else "DEAD")
        Spacer(Modifier.height(4.dp))
        StatBar("ARMOR", player.armor, Palette.CT.copy(alpha = 0.8f), suffix = if (player.helmet) "HELMET" else null)
        if (player.flashed > 0) {
            Spacer(Modifier.height(4.dp))
            StatBar("FLASH", player.flashed * 100 / 255, Color.White)
        }
        Spacer(Modifier.height(10.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(18.dp)) {
            Stat("K / A / D", "${player.kills} / ${player.assists} / ${player.deaths}")
            Stat("ROUND", "${player.roundKills}K" + (if (player.roundHs > 0) " (${player.roundHs} HS)" else "") + " · ${player.roundDmg} dmg")
            Stat("EQUIP", Format.money(player.equip))
        }
        if (player.weapons.isNotEmpty()) {
            Spacer(Modifier.height(10.dp))
            WeaponList(player.weapons)
        }
    }
}

@Composable
private fun StatBar(label: String, value: Int, color: Color, suffix: String? = null) {
    Row(verticalAlignment = Alignment.CenterVertically) {
        Text(label, Modifier.width(52.dp), style = MaterialTheme.typography.labelSmall, color = Palette.TextMuted)
        Box(Modifier.weight(1f).height(8.dp).background(Palette.Outline, RoundedCornerShape(4.dp))) {
            Box(
                Modifier.fillMaxWidth(value.coerceIn(0, 100) / 100f).fillMaxHeight().background(color, RoundedCornerShape(4.dp)),
            )
        }
        Text(
            "$value",
            Modifier.width(36.dp),
            textAlign = TextAlign.End,
            style = MaterialTheme.typography.labelMedium,
            color = Palette.Text,
        )
        if (suffix != null) {
            Text(suffix, Modifier.padding(start = 6.dp), style = MaterialTheme.typography.labelSmall, color = Palette.TextMuted)
        }
    }
}

@Composable
private fun Stat(label: String, value: String) {
    Column {
        Caption(label)
        Text(value, style = MaterialTheme.typography.bodyMedium, color = Palette.Text)
    }
}

@Composable
private fun WeaponList(weapons: List<Weapon>) {
    val (grenades, others) = weapons.partition { it.type == "Grenade" }
    Column(verticalArrangement = Arrangement.spacedBy(2.dp)) {
        for (w in others) {
            val active = w.state == "active"
            Row(
                Modifier
                    .fillMaxWidth()
                    .background(if (active) Palette.SurfaceHigh else Color.Transparent, RoundedCornerShape(6.dp))
                    .padding(horizontal = 8.dp, vertical = 3.dp),
            ) {
                Text(
                    Format.weapon(w.name),
                    Modifier.weight(1f),
                    style = MaterialTheme.typography.bodyMedium,
                    color = if (active) Palette.Text else Palette.TextMuted,
                    fontWeight = if (active) FontWeight.SemiBold else FontWeight.Normal,
                )
                val clip = w.clip
                if (clip != null) {
                    val clipMax = w.clipMax
                    val low = clipMax != null && clipMax > 0 && clip * 4 <= clipMax
                    Text(
                        "$clip / ${w.reserve ?: 0}",
                        style = MaterialTheme.typography.bodyMedium,
                        color = if (low) Palette.Warn else Palette.Text,
                    )
                }
            }
        }
        if (grenades.isNotEmpty()) {
            Text(
                grenades.joinToString("  ·  ") { g ->
                    Format.weapon(g.name) + (g.reserve?.takeIf { it > 1 }?.let { " ×$it" } ?: "")
                },
                Modifier.padding(horizontal = 8.dp, vertical = 3.dp),
                style = MaterialTheme.typography.bodySmall,
                color = Palette.TextMuted,
            )
        }
    }
}

// --- teams ----------------------------------------------------------------------------------------

@Composable
fun EconomyRow(ctPlayers: List<Player>, tPlayers: List<Player>, ct: TeamInfo?, t: TeamInfo?) {
    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        TeamEconomy(Team.CT, ctPlayers, ct, Modifier.weight(1f))
        TeamEconomy(Team.T, tPlayers, t, Modifier.weight(1f))
    }
}

@Composable
private fun TeamEconomy(team: Team, players: List<Player>, info: TeamInfo?, modifier: Modifier) {
    Panel(modifier) {
        Caption(if (team == Team.CT) "CT ECONOMY" else "T ECONOMY", teamColor(team))
        Spacer(Modifier.height(4.dp))
        Text(Format.money(players.sumOf { it.money }), style = MaterialTheme.typography.titleMedium, color = Palette.Text)
        Text("Equipped ${Format.money(players.sumOf { it.equip })}", style = MaterialTheme.typography.bodySmall, color = Palette.TextMuted)
        Text(
            "Next loss ${Format.money(Economy.nextLossBonus(info?.losses ?: 0))}",
            style = MaterialTheme.typography.bodySmall,
            color = Palette.TextMuted,
        )
    }
}

@Composable
fun TeamRoster(team: Team, players: List<Player>, focusId: String?, bombCarrier: String?) {
    if (players.isEmpty()) return
    Panel {
        Caption(if (team == Team.CT) "COUNTER-TERRORISTS" else "TERRORISTS", teamColor(team))
        Spacer(Modifier.height(6.dp))
        for (p in players) RosterRow(p, highlighted = p.id == focusId, hasBomb = p.id == bombCarrier || p.hasBomb)
    }
}

@Composable
private fun RosterRow(p: Player, highlighted: Boolean, hasBomb: Boolean) {
    Row(
        Modifier
            .fillMaxWidth()
            .alpha(if (p.alive) 1f else 0.4f)
            .background(if (highlighted) Palette.SurfaceHigh else Color.Transparent, RoundedCornerShape(6.dp))
            .padding(horizontal = 6.dp, vertical = 4.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(p.slot?.let { "${it % 10}" }.orEmpty(), Modifier.width(14.dp), style = MaterialTheme.typography.labelSmall, color = Palette.TextMuted)
        Text(p.name, Modifier.weight(1f), style = MaterialTheme.typography.bodyMedium, color = Palette.Text, maxLines = 1, overflow = TextOverflow.Ellipsis)
        Box(Modifier.width(48.dp).height(6.dp).background(Palette.Outline, RoundedCornerShape(3.dp))) {
            Box(Modifier.fillMaxWidth(p.hp.coerceIn(0, 100) / 100f).fillMaxHeight().background(hpColor(p.hp), RoundedCornerShape(3.dp)))
        }
        Text("${p.hp}", Modifier.width(30.dp), textAlign = TextAlign.End, style = MaterialTheme.typography.labelMedium, color = Palette.Text)
        Text(
            when {
                hasBomb -> "C4"
                p.defuser -> "KIT"
                p.helmet -> "A+H"
                p.armor > 0 -> "A"
                else -> ""
            },
            Modifier.width(34.dp),
            textAlign = TextAlign.Center,
            style = MaterialTheme.typography.labelSmall,
            color = if (hasBomb) Palette.Danger else if (p.defuser) Palette.CT else Palette.TextMuted,
        )
        Text(Format.money(p.money), Modifier.width(58.dp), textAlign = TextAlign.End, style = MaterialTheme.typography.labelMedium, color = Palette.Good)
        Text(
            p.activeWeapon?.let { Format.weapon(it.name) }.orEmpty(),
            Modifier.width(70.dp).padding(start = 6.dp),
            style = MaterialTheme.typography.labelSmall,
            color = Palette.TextMuted,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
        )
    }
}
