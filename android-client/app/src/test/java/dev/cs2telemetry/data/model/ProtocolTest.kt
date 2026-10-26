package dev.cs2telemetry.data.model

import kotlinx.serialization.SerializationException
import kotlinx.serialization.serializer
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class ProtocolTest {
    private val serializer = serializer<HostMessage>()

    private fun decode(text: String): HostMessage = ProtocolJson.decodeFromString(serializer, text)

    /** state_spectator.json is real host output, regenerated with pc-host/tools/export_fixture.py. */
    @Test
    fun parsesHostStateFixture() {
        val text = javaClass.classLoader!!.getResource("state_spectator.json")!!.readText()
        val message = decode(text) as HostMessage.State
        val state = message.d

        assertEquals(GameMode.SPECTATOR, state.mode)
        assertEquals("de_dust2", state.map?.name)
        assertEquals(RadarInfo(-2476f, 3239f, 4.4f, "de_dust2"), state.map?.radar)
        assertEquals(10, state.players.size)
        assertEquals(5, state.teamPlayers(Team.CT).size)
        assertEquals(5, state.teamPlayers(Team.T).size)

        val focus = requireNotNull(state.focusPlayer)
        assertEquals(3, focus.pos?.size)
        assertNotNull(focus.yaw)
        assertTrue(focus.weapons.isNotEmpty())

        val smoke = state.grenades.first { it.type == "smoke" }
        assertTrue((smoke.effect ?: 0f) > 0f)
        assertTrue(state.grenades.first { it.type == "inferno" }.flames.isNotEmpty())
        assertEquals("carried", state.bomb?.state)
        assertTrue(state.players.any { it.hasBomb })
    }

    @Test
    fun parsesHelloAndHeartbeat() {
        assertEquals(HostMessage.Hello(1, "cs2-telemetry-host/1.0.0", 2f, 30f), decode("""{"t":"hello","v":1,"server":"cs2-telemetry-host/1.0.0","hb":2.0,"maxHz":30}"""))
        assertEquals(HostMessage.Heartbeat(12, null, 1), decode("""{"t":"hb","seq":12,"gsiAge":null,"clients":1}"""))
        assertEquals(HostMessage.Heartbeat(12, 0.25f, 1), decode("""{"t":"hb","seq":12,"gsiAge":0.25,"clients":1}"""))
    }

    @Test
    fun toleratesNewFieldsAndUnknownEnumValues() {
        val message = decode(
            """{"t":"state","seq":3,"d":{"mode":"coach","futureField":{"x":1},
               "players":[{"id":"1","team":"SPEC","hp":50,"newStat":7}]}}""",
        ) as HostMessage.State
        assertEquals(GameMode.MENU, message.d.mode) // unknown mode coerced to the default
        assertNull(message.d.players.single().team)
        assertEquals(50, message.d.players.single().hp)
    }

    @Test(expected = SerializationException::class)
    fun unknownMessageTypeIsRejected() {
        decode("""{"t":"telemetry-v2","x":1}""")
    }

    @Test
    fun minimalStateUsesDefaults() {
        val state = (decode("""{"t":"state","seq":1,"d":{"mode":"menu","players":[],"grenades":[]}}""") as HostMessage.State).d
        assertNull(state.map)
        assertNull(state.focusPlayer)
        assertTrue(state.players.isEmpty())
    }
}
