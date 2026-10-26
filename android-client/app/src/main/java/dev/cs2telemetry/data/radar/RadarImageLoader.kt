package dev.cs2telemetry.data.radar

import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.util.LruCache
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.asImageBitmap
import dev.cs2telemetry.data.net.Endpoint
import java.io.IOException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import okhttp3.Request

/**
 * Fetches radar images from the host (GET /radar/<image>.png), so the images live in one place on
 * the PC and never have to be bundled into the APK. Decoded as HARDWARE bitmaps: they are uploaded
 * to the GPU once and drawn by the hardware-accelerated canvas without per-frame copies.
 */
class RadarImageLoader(private val http: OkHttpClient) {
    private val cache = LruCache<String, ImageBitmap>(MAX_CACHED_IMAGES)

    /** The image, or null if the host has none for this map (the minimap then draws a grid). */
    suspend fun load(endpoint: Endpoint, image: String): ImageBitmap? {
        val url = endpoint.radarUrl(image)
        val key = url.toString()
        cache.get(key)?.let { return it }
        return withContext(Dispatchers.IO) {
            try {
                http.newCall(Request.Builder().url(url).build()).execute().use { response ->
                    if (!response.isSuccessful) return@withContext null
                    val bytes = response.body?.bytes() ?: return@withContext null
                    decode(bytes)?.also { cache.put(key, it) }
                }
            } catch (e: IOException) {
                null
            }
        }
    }

    private fun decode(bytes: ByteArray): ImageBitmap? {
        val hardware = BitmapFactory.Options().apply { inPreferredConfig = Bitmap.Config.HARDWARE }
        val bitmap = BitmapFactory.decodeByteArray(bytes, 0, bytes.size, hardware)
            ?: BitmapFactory.decodeByteArray(bytes, 0, bytes.size)
            ?: return null
        return bitmap.asImageBitmap()
    }

    private companion object {
        const val MAX_CACHED_IMAGES = 4 // upper + lower level of the current and previous map
    }
}
