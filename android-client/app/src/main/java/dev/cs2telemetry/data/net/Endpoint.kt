package dev.cs2telemetry.data.net

import okhttp3.HttpUrl

/**
 * Where the PC host's bridge is reachable from the phone.
 * USB with `adb reverse`: 127.0.0.1:8090 (the default). USB tethering or Wi-Fi: the PC's address.
 */
data class Endpoint(
    val host: String = DEFAULT_HOST,
    val port: Int = DEFAULT_PORT,
    val token: String = "",
) {
    val label: String get() = "$host:$port"

    fun webSocketUrl(): HttpUrl = baseUrl().newBuilder()
        .addPathSegment("ws")
        .apply { if (token.isNotEmpty()) addQueryParameter("token", token) }
        .build()

    fun radarUrl(image: String): HttpUrl = baseUrl().newBuilder()
        .addPathSegment("radar")
        .addPathSegment("$image.png")
        .build()

    private fun baseUrl(): HttpUrl = HttpUrl.Builder().scheme("http").host(host).port(port).build()

    companion object {
        const val DEFAULT_HOST = "127.0.0.1"
        const val DEFAULT_PORT = 8090

        /** Validates user input; null when the host or port would not make a usable URL. */
        fun parseOrNull(host: String, port: String, token: String): Endpoint? {
            val candidate = Endpoint(host.trim(), port.trim().toIntOrNull() ?: return null, token.trim())
            return runCatching { candidate.webSocketUrl() }.map { candidate }.getOrNull()
        }
    }
}
