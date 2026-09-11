package com.kaoss.studio

import android.Manifest
import android.app.Activity
import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.content.pm.PackageManager
import android.hardware.usb.UsbConstants
import android.hardware.usb.UsbDevice
import android.hardware.usb.UsbManager
import android.os.Build
import android.os.Bundle
import android.webkit.PermissionRequest
import android.webkit.WebChromeClient
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.core.content.ContextCompat

class MainActivity : Activity() {
    private val requestCode = 8801
    private val usbPermissionRequestCode = 8802
    private val runtimeGrants = LinkedHashMap<String, Boolean>()
    private var bridge: KaossJsBridge? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        bridge = KaossJsBridge(this)
        requestRuntimePermissions()
        registerUsbHotplugReceiver()
        val view = WebView(this)
        val settings: WebSettings = view.settings
        settings.javaScriptEnabled = true
        settings.domStorageEnabled = true
        settings.mediaPlaybackRequiresUserGesture = false
        settings.allowFileAccess = true
        view.webViewClient = WebViewClient()
        view.webChromeClient = object : WebChromeClient() {
            override fun onPermissionRequest(request: PermissionRequest) {
                // Der WebView-Host reicht die nativen Runtime-Grants an die PWA durch.
                request.grant(request.resources)
            }
        }
        view.addJavascriptInterface(bridge, "KaossNativeBridge")
        view.loadUrl("file:///android_asset/www/index.html")
        setContentView(view)
    }

    override fun onDestroy() {
        bridge?.stopAudioCapture()
        unregisterReceiver(usbReceiver)
        super.onDestroy()
    }

    fun permissionGrants(): Map<String, Boolean> {
        return runtimeGrants.toMap()
    }

    private fun requestRuntimePermissions() {
        val needed = mutableListOf(Manifest.permission.RECORD_AUDIO)
        if (Build.VERSION.SDK_INT >= 31) {
            needed += Manifest.permission.BLUETOOTH_CONNECT
            needed += Manifest.permission.BLUETOOTH_SCAN
        }
        val missing = needed.filter { checkSelfPermission(it) != PackageManager.PERMISSION_GRANTED }
        if (missing.isNotEmpty()) {
            requestPermissions(missing.toTypedArray(), requestCode)
        }
    }

    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        for ((index, permission) in permissions.withIndex()) {
            runtimeGrants[permission] = grantResults[index] == PackageManager.PERMISSION_GRANTED
        }
    }

    // ------------------------------------------------------------------ //
    // USB Audio Class hotplug + permission intent flow
    // ------------------------------------------------------------------ //
    private val usbReceiver = object : BroadcastReceiver() {
        override fun onReceive(context: Context, intent: Intent) {
            when (intent.action) {
                UsbManager.ACTION_USB_DEVICE_ATTACHED,
                UsbManager.ACTION_USB_ACCESSORY_ATTACHED -> requestUsbAudioPermission()
            }
        }
    }

    private fun registerUsbHotplugReceiver() {
        val filter = IntentFilter().apply {
            addAction(UsbManager.ACTION_USB_DEVICE_ATTACHED)
            addAction(UsbManager.ACTION_USB_ACCESSORY_ATTACHED)
        }
        ContextCompat.registerReceiver(this, usbReceiver, filter, ContextCompat.RECEIVER_NOT_EXPORTED)
    }

    private fun requestUsbAudioPermission() {
        val manager = getSystemService(Context.USB_SERVICE) as? UsbManager ?: return
        val audioDevice = manager.deviceList.values.firstOrNull { device ->
            (0 until device.interfaceCount).any {
                device.getInterface(it).interfaceClass == UsbConstants.USB_CLASS_AUDIO
            }
        } ?: return
        if (manager.hasPermission(audioDevice)) return
        val pending = PendingIntent.getBroadcast(
            this,
            usbPermissionRequestCode,
            Intent("com.kaoss.studio.USB_PERMISSION"),
            PendingIntent.FLAG_IMMUTABLE,
        )
        manager.requestPermission(audioDevice, pending)
    }

    /** Wird in Produktion per Broadcast-Empfänger für USB_PERMISSION ergänzt. */
    fun describeUsb(device: UsbDevice): String {
        val audio = (0 until device.interfaceCount).any {
            device.getInterface(it).interfaceClass == UsbConstants.USB_CLASS_AUDIO
        }
        return "{\"vid\":\"${device.vendorId.toString(16)}\",\"pid\":\"${device.productId.toString(16)}\"," +
            "\"product\":\"${device.productName ?: device.deviceName}\",\"uac2_candidate\":$audio}"
    }
}
