package dev.cs2telemetry.ui.dashboard

import dev.cs2telemetry.data.model.BombInfo
import dev.cs2telemetry.data.model.GameMode
import dev.cs2telemetry.data.model.MapInfo
import dev.cs2telemetry.data.model.PhaseInfo
import dev.cs2telemetry.data.model.Player
import dev.cs2telemetry.data.model.RadarInfo
import dev.cs2telemetry.data.model.RoundInfo
import dev.cs2telemetry.data.model.RoundResult
import dev.cs2telemetry.data.model.Team
import dev.cs2telemetry.data.model.TeamInfo
import dev.cs2telemetry.data.model.TelemetryState
import dev.cs2telemetry.data.model.Weapon

/** Static sample match for Android Studio previews. */
internal object PreviewData {
    private val rifle = Weapon("ak47", "Rifle", "active", clip = 27, clipMax = 30, reserve = 90)
    private val m4 = Weapon("m4a1_silencer", "Rifle", "active", clip = 20, clipMax = 20, reserve = 80)

    private fun player(i: Int, team: Team, x: Float, y: Float, yaw: Float, hp: Int = 100) = Player(
        id = "7656119800000000$i",
        name = listOf("Kestrel", "Vanta", "Moro", "Ditch", "Pillar", "Halcyon", "Brisk", "Oslo", "Quill", "Ember")[i],
        team = team,
        slot = (i + 1) % 10,
        hp = hp,
        armor = if (hp > 0) 100 else 0,
        helmet = hp > 0,
        money = 1250 + i * 650,
        equip = if (hp > 0) 4700 else 0,
        kills = 9 - i % 4,
        deaths = 6 + i % 3,
        assists = i % 4,
        pos = listOf(x, y, 96f),
        yaw = yaw,
        weapons = if (hp > 0) listOf(Weapon("knife", "Knife", "holstered"), if (team == Team.T) rifle else m4) else emptyList(),
    )

    val state = TelemetryState(
        mode = GameMode.SPECTATOR,
        map = MapInfo(
            name = "de_dust2",
            phase = "live",
            round = 11,
            ct = TeamInfo(score = 6, losses = 1),
            t = TeamInfo(score = 5),
            radar = RadarInfo(posX = -2476f, posY = 3239f, scale = 4.4f, image = "de_dust2"),
            history = List(11) { RoundResult(it + 1, if (it % 3 == 0) Team.T else Team.CT, if (it % 3 == 0) "bomb" else "elimination") },
        ),
        round = RoundInfo(phase = "live"),
        phase = PhaseInfo("live", 74.3f),
        focus = "76561198000000000",
        players = listOf(
            player(0, Team.T, 1100f, 1700f, 80f, hp = 64),
            player(1, Team.T, -400f, 1300f, 60f),
            player(2, Team.T, -1700f, 1300f, 90f),
            player(3, Team.T, -800f, 400f, 45f, hp = 0),
            player(4, Team.T, 1300f, 1100f, 100f),
            player(5, Team.CT, 1150f, 2400f, -100f),
            player(6, Team.CT, 690f, 1900f, -150f, hp = 37),
            player(7, Team.CT, -1600f, 2400f, -80f),
            player(8, Team.CT, -400f, 1800f, -90f),
            player(9, Team.CT, -1300f, 2200f, -60f),
        ),
        bomb = BombInfo(state = "carried", carrier = "76561198000000000"),
    )
}
