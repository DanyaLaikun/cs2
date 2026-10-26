package dev.cs2telemetry.ui.dashboard

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import dev.cs2telemetry.data.model.RadarInfo
import dev.cs2telemetry.data.net.ConnectionStatus
import dev.cs2telemetry.data.net.Endpoint
import dev.cs2telemetry.data.net.HostHealth
import dev.cs2telemetry.data.net.Snapshot
import dev.cs2telemetry.data.net.TelemetryClient
import dev.cs2telemetry.data.radar.RadarImageLoader
import dev.cs2telemetry.data.settings.EndpointStore
import dev.cs2telemetry.ui.minimap.RadarLayers
import java.util.concurrent.TimeUnit
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.flow.mapLatest
import kotlinx.coroutines.flow.stateIn
import okhttp3.OkHttpClient

/** Owns the host link for the screen's lifetime; the UI starts and stops it with the lifecycle. */
class DashboardViewModel(application: Application) : AndroidViewModel(application) {
    private val store = EndpointStore(application)
    private val http = OkHttpClient.Builder()
        .connectTimeout(3, TimeUnit.SECONDS)
        .readTimeout(5, TimeUnit.SECONDS)
        .build()
    private val client = TelemetryClient(http, viewModelScope)
    private val radarLoader = RadarImageLoader(http)
    private var started = false

    private val _endpoint = MutableStateFlow(store.load())
    val endpoint: StateFlow<Endpoint> = _endpoint.asStateFlow()

    val status: StateFlow<ConnectionStatus> = client.status
    val snapshot: StateFlow<Snapshot?> = client.snapshot
    val health: StateFlow<HostHealth?> = client.health

    /** Radar images follow the map; a (re)connect retries images that failed while the link was down. */
    @OptIn(ExperimentalCoroutinesApi::class)
    val radar: StateFlow<RadarLayers> = combine(
        _endpoint,
        client.snapshot.map { it?.state?.map?.radar }.distinctUntilChanged(),
        client.status.map { it is ConnectionStatus.Connected }.distinctUntilChanged(),
    ) { endpoint, info, _ -> endpoint to info }
        .mapLatest { (endpoint, info) -> loadRadar(endpoint, info) }
        .stateIn(viewModelScope, SharingStarted.Eagerly, RadarLayers.None)

    fun onStart() {
        started = true
        client.connect(_endpoint.value)
    }

    fun onStop() {
        started = false
        client.disconnect()
    }

    fun updateEndpoint(endpoint: Endpoint) {
        store.save(endpoint)
        _endpoint.value = endpoint
        if (started) client.connect(endpoint)
    }

    private suspend fun loadRadar(endpoint: Endpoint, info: RadarInfo?): RadarLayers {
        if (info == null) return RadarLayers.None
        return RadarLayers(
            image = info.image,
            upper = radarLoader.load(endpoint, info.image),
            lower = info.lowerImage?.let { radarLoader.load(endpoint, it) },
        )
    }

    override fun onCleared() {
        client.disconnect()
        http.dispatcher.executorService.shutdown()
        http.connectionPool.evictAll()
    }
}
