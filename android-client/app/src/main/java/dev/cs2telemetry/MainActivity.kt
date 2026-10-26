package dev.cs2telemetry

import android.os.Bundle
import android.view.WindowManager
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import dev.cs2telemetry.ui.dashboard.DashboardRoute
import dev.cs2telemetry.ui.theme.TelemetryTheme

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        // A second screen is useless if it dims mid-round; the device is on USB power anyway.
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        setContent {
            TelemetryTheme {
                DashboardRoute()
            }
        }
    }
}
