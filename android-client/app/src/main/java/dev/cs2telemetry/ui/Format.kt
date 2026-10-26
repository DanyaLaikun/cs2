package dev.cs2telemetry.ui

import java.util.Locale

/** Display formatting for game values. */
object Format {
    private val weaponNames = mapOf(
        "ak47" to "AK-47", "m4a1" to "M4A4", "m4a1_silencer" to "M4A1-S", "awp" to "AWP",
        "famas" to "FAMAS", "galilar" to "Galil AR", "aug" to "AUG", "sg556" to "SG 553",
        "ssg08" to "SSG 08", "scar20" to "SCAR-20", "g3sg1" to "G3SG1",
        "glock" to "Glock-18", "hkp2000" to "P2000", "usp_silencer" to "USP-S", "p250" to "P250",
        "fiveseven" to "Five-SeveN", "tec9" to "Tec-9", "cz75a" to "CZ75-Auto", "elite" to "Dual Berettas",
        "deagle" to "Desert Eagle", "revolver" to "R8 Revolver",
        "mac10" to "MAC-10", "mp9" to "MP9", "mp7" to "MP7", "mp5sd" to "MP5-SD", "ump45" to "UMP-45",
        "p90" to "P90", "bizon" to "PP-Bizon",
        "nova" to "Nova", "xm1014" to "XM1014", "mag7" to "MAG-7", "sawedoff" to "Sawed-Off",
        "m249" to "M249", "negev" to "Negev", "taser" to "Zeus x27",
        "hegrenade" to "HE", "flashbang" to "Flash", "smokegrenade" to "Smoke", "molotov" to "Molotov",
        "incgrenade" to "Incendiary", "decoy" to "Decoy", "c4" to "C4",
    )

    fun weapon(name: String): String = weaponNames[name]
        ?: if (name.startsWith("knife") || name == "bayonet") "Knife" else name.replace('_', ' ').uppercase(Locale.US)

    fun money(value: Int): String = "$" + String.format(Locale.US, "%,d", value)

    fun clock(seconds: Float): String {
        val total = seconds.coerceAtLeast(0f).toInt()
        return String.format(Locale.US, "%d:%02d", total / 60, total % 60)
    }

    fun upper(text: String?): String = text?.replace('_', ' ')?.uppercase(Locale.US).orEmpty()
}

object Economy {
    /** CS2 loss bonus paid on the next lost round: $1400, +$500 per consecutive loss, capped at $3400. */
    fun nextLossBonus(consecutiveLosses: Int): Int = 1400 + 500 * consecutiveLosses.coerceIn(0, 4)
}
