# kotlinx.serialization: keep generated serializers for the protocol models.
# (Recent library versions ship equivalent rules; these keep release builds safe regardless.)
-keepattributes *Annotation*, InnerClasses
-dontnote kotlinx.serialization.**
-keepclassmembers class dev.cs2telemetry.data.model.** {
    *** Companion;
}
-keepclasseswithmembers class dev.cs2telemetry.data.model.** {
    kotlinx.serialization.KSerializer serializer(...);
}
-keep,includedescriptorclasses class dev.cs2telemetry.data.model.**$$serializer { *; }
