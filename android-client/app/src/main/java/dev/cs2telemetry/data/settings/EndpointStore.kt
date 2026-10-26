package dev.cs2telemetry.data.settings

import android.content.Context
import androidx.core.content.edit
import dev.cs2telemetry.data.net.Endpoint

/** Persists the host address the user configured. */
class EndpointStore(context: Context) {
    private val prefs = context.getSharedPreferences("host_link", Context.MODE_PRIVATE)

    fun load(): Endpoint = Endpoint(
        host = prefs.getString(KEY_HOST, null) ?: Endpoint.DEFAULT_HOST,
        port = prefs.getInt(KEY_PORT, Endpoint.DEFAULT_PORT),
        token = prefs.getString(KEY_TOKEN, null).orEmpty(),
    )

    fun save(endpoint: Endpoint) = prefs.edit {
        putString(KEY_HOST, endpoint.host)
        putInt(KEY_PORT, endpoint.port)
        putString(KEY_TOKEN, endpoint.token)
    }

    private companion object {
        const val KEY_HOST = "host"
        const val KEY_PORT = "port"
        const val KEY_TOKEN = "token"
    }
}
