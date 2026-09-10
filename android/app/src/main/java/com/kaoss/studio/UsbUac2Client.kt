package com.kaoss.studio

import android.content.Context
import android.hardware.usb.UsbConstants
import android.hardware.usb.UsbDevice
import android.hardware.usb.UsbManager

/** Client-side UAC2 VID/PID hotplug against Android UsbManager. */
class UsbUac2Client(private val context: Context) {
    fun snapshot(): String {
        val manager = context.getSystemService(Context.USB_SERVICE) as? UsbManager
            ?: return "{\"ok\":false,\"count\":0,\"devices\":[]}"
        val devices = manager.deviceList.values.map { device -> describe(device) }
        return "{\"ok\":true,\"protocol\":\"UAC2\",\"count\":${devices.size},\"devices\":[${devices.joinToString(",")}]}"
    }

    private fun describe(device: UsbDevice): String {
        val audio = (0 until device.interfaceCount).any {
            device.getInterface(it).interfaceClass == UsbConstants.USB_CLASS_AUDIO
        }
        return "{\"vid\":\"${device.vendorId.toString(16)}\",\"pid\":\"${device.productId.toString(16)}\",\"product\":\"${device.productName ?: device.deviceName}\",\"uac2_candidate\":$audio}"
    }
}
