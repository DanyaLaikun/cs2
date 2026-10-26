package dev.cs2telemetry.data.model

import androidx.compose.runtime.Immutable
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json

/**
 * Wire format of the PC host's WebSocket stream (docs/PROTOCOL.md). The host omits absent values
 * instead of sending null, so every field has a default. Models are deeply immutable, which lets
 * Compose skip recomposing panels whose slice of the state did not change between frames.
 */
const val PROTOCOL_VERSION = 1

val ProtocolJson = Json {
    ignoreUnknownKeys = true // newer hosts may add fields
    explicitNulls = false
    coerceInputValues = true // unknown enum values fall back to the property default
    classDiscriminator = "t"
}

@Serializable
sealed interface HostMessage {
    @Serializable
    @SerialName("hello")
    data class Hello(
        val v: Int = PROTOCOL_VERSION,
        val server: String = "",
        val hb: Float = 2f,
        val maxHz: Float = 0f,
    ) : HostMessage

    @Serializable
    @SerialName("state")
    data class State(val seq: Long = 0, val d: TelemetryState = TelemetryState()) : HostMessage

    @Serializable
    @SerialName("hb")
    data class Heartbeat(val seq: Long = 0, val gsiAge: Float? = null, val clients: Int = 0) : HostMessage
}

@Serializable
enum class GameMode {
    @SerialName("menu") MENU,
    @SerialName("player") PLAYER,
    @SerialName("spectator") SPECTATOR,
}

@Serializable
enum class Team {
    @SerialName("CT") CT,
    @SerialName("T") T,
}

@Immutable
@Serializable
data class TelemetryState(
    val mode: GameMode = GameMode.MENU,
    val provider: ProviderInfo? = null,
    val map: MapInfo? = null,
    val round: RoundInfo? = null,
    val phase: PhaseInfo? = null,
    val focus: String? = null,
    val players: List<Player> = emptyList(),
    val bomb: BombInfo? = null,
    val grenades: List<Grenade> = emptyList(),
)

@Immutable
@Serializable
data class ProviderInfo(
    val name: String? = null,
    val steamId: String? = null,
    val version: Int? = null,
    val ts: Long? = null,
)

@Immutable
@Serializable
data class MapInfo(
    val name: String = "",
    val mode: String? = null,
    val phase: String? = null,
    val round: Int = 0,
    val ct: TeamInfo = TeamInfo(),
    val t: TeamInfo = TeamInfo(),
    val radar: RadarInfo? = null,
    val history: List<RoundResult> = emptyList(),
)

@Immutable
@Serializable
data class TeamInfo(
    val score: Int = 0,
    val name: String? = null,
    val losses: Int = 0,
    val timeouts: Int = 0,
    val seriesWins: Int = 0,
)

/** World-to-radar calibration: radar px = (x - posX) / scale, (posY - y) / scale on a 1024 px radar. */
@Immutable
@Serializable
data class RadarInfo(
    val posX: Float,
    val posY: Float,
    val scale: Float,
    val image: String,
    val splitZ: Float? = null,
    val lowerImage: String? = null,
)

@Immutable
@Serializable
data class RoundResult(val r: Int, val w: Team? = null, val why: String? = null)

@Immutable
@Serializable
data class RoundInfo(val phase: String? = null, val bomb: String? = null, val winTeam: Team? = null)

@Immutable
@Serializable
data class PhaseInfo(val name: String? = null, val endsIn: Float? = null)

@Immutable
@Serializable
data class Player(
    val id: String,
    val name: String = "?",
    val team: Team? = null,
    val slot: Int? = null,
    val hp: Int = 0,
    val armor: Int = 0,
    val helmet: Boolean = false,
    val defuser: Boolean = false,
    val flashed: Int = 0,
    val smoked: Int = 0,
    val burning: Int = 0,
    val money: Int = 0,
    val equip: Int = 0,
    val roundKills: Int = 0,
    val roundHs: Int = 0,
    val roundDmg: Int = 0,
    val kills: Int = 0,
    val assists: Int = 0,
    val deaths: Int = 0,
    val mvps: Int = 0,
    val score: Int = 0,
    /** World position [x, y, z] in game units. */
    val pos: List<Float>? = null,
    /** View direction in degrees: 0 = +X (east), 90 = +Y (north). */
    val yaw: Float? = null,
    val pitch: Float? = null,
    val weapons: List<Weapon> = emptyList(),
    val activity: String? = null,
) {
    val alive: Boolean get() = hp > 0
    val activeWeapon: Weapon? get() = weapons.firstOrNull { it.state == "active" }
    val hasBomb: Boolean get() = weapons.any { it.name == "c4" }
}

@Immutable
@Serializable
data class Weapon(
    val name: String,
    val type: String? = null,
    val state: String? = null,
    val clip: Int? = null,
    val clipMax: Int? = null,
    val reserve: Int? = null,
)

@Immutable
@Serializable
data class BombInfo(
    val state: String? = null,
    val pos: List<Float>? = null,
    val carrier: String? = null,
    val countdown: Float? = null,
)

@Immutable
@Serializable
data class Grenade(
    val id: String,
    val type: String? = null,
    val owner: String? = null,
    val pos: List<Float>? = null,
    val life: Float? = null,
    /** Seconds since the effect (smoke cloud) deployed; 0 while still in flight. */
    val effect: Float? = null,
    val flames: List<List<Float>> = emptyList(),
)

val TelemetryState.focusPlayer: Player?
    get() = focus?.let { id -> players.firstOrNull { it.id == id } }

/** Players of one side in observer-slot order (slot 0 is the tenth key, so it sorts last). */
fun TelemetryState.teamPlayers(team: Team): List<Player> =
    players.filter { it.team == team }.sortedBy { p -> p.slot?.let { if (it == 0) 10 else it } ?: 99 }
