package org.openbabymonitor.app

import androidx.annotation.StringRes

/**
 * The events the device reports, and what each one should look like on the
 * phone. The names mirror the ones in control/events.py.
 */
object EventTypes {

    const val CRYING = "crying"
    const val BABBLING = "babbling"
    const val SOUND = "sound"
    const val TRANSMISSION = "transmission"
    const val MOTION = "motion"
    const val OUTSIDE = "outside"
    const val ASLEEP = "asleep"
    const val AWAKE = "awake"
    const val RECORDING_STOPPED = "rec_stopped"

    /** The unit the value carried by an event is measured in, if any. */
    private const val DECIBEL = "dB"
    private const val PERCENT = "%"

    data class Descriptor(
        val type: String,
        @StringRes val label: Int,
        val urgent: Boolean,
        val onByDefault: Boolean,
        val unit: String?
    )

    /** In the order they are offered in the settings. */
    val all: List<Descriptor> = listOf(
        Descriptor(CRYING, R.string.event_crying, urgent = true, onByDefault = true, unit = DECIBEL),
        Descriptor(OUTSIDE, R.string.event_outside, urgent = true, onByDefault = true, unit = PERCENT),
        Descriptor(MOTION, R.string.event_motion, urgent = false, onByDefault = true, unit = PERCENT),
        Descriptor(BABBLING, R.string.event_babbling, urgent = false, onByDefault = false, unit = DECIBEL),
        Descriptor(SOUND, R.string.event_sound, urgent = false, onByDefault = false, unit = DECIBEL),
        Descriptor(TRANSMISSION, R.string.event_transmission, urgent = false, onByDefault = false, unit = DECIBEL),
        Descriptor(ASLEEP, R.string.event_asleep, urgent = false, onByDefault = false, unit = null),
        Descriptor(AWAKE, R.string.event_awake, urgent = false, onByDefault = false, unit = null),
        Descriptor(RECORDING_STOPPED, R.string.event_rec_stopped, urgent = false, onByDefault = false, unit = null)
    )

    private val byType: Map<String, Descriptor> = all.associateBy { it.type }

    fun of(type: String): Descriptor? = byType[type]

    fun alertsByDefault(type: String): Boolean = byType[type]?.onByDefault ?: false
}
