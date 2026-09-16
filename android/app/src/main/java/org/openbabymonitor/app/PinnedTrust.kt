package org.openbabymonitor.app

import java.net.InetSocketAddress
import java.net.Socket
import java.security.MessageDigest
import java.security.cert.CertificateException
import java.security.cert.X509Certificate
import javax.net.ssl.HostnameVerifier
import javax.net.ssl.SSLContext
import javax.net.ssl.SSLSession
import javax.net.ssl.SSLSocket
import javax.net.ssl.SSLSocketFactory
import javax.net.ssl.TrustManager
import javax.net.ssl.X509TrustManager

/**
 * Deciding which server the app is willing to talk to.
 *
 * The baby monitor signs its own certificate, so there is no authority that can
 * vouch for it. Instead the app remembers the exact certificate it was paired
 * with and refuses every other one. That is stronger than trusting a public
 * authority: it accepts one specific server rather than any server some
 * authority is willing to sign for.
 *
 * The pairing itself is the weak moment. The first connection has nothing to
 * check against, so the fingerprint is shown to the user, who compares it with
 * the one the device printed during installation. After that it is pinned and a
 * changed certificate is a hard failure, not a warning to click through.
 */
object PinnedTrust {

    /** SHA-256 over the certificate as the server sent it. */
    fun fingerprintOf(certificate: X509Certificate): String {
        val digest = MessageDigest.getInstance("SHA-256").digest(certificate.encoded)
        return digest.joinToString("") { "%02X".format(it) }
    }

    /** The same fingerprint in the colon separated form openssl prints. */
    fun formatForDisplay(fingerprint: String): String =
        fingerprint.chunked(2).joinToString(":")

    fun matches(certificate: X509Certificate, pin: String): Boolean {
        val expected = pin.replace(":", "").uppercase()
        // A length-independent comparison is pointless here, the value is public,
        // but keeping it constant time costs nothing
        val actual = fingerprintOf(certificate)
        if (expected.length != actual.length) return false
        var difference = 0
        for (i in expected.indices) {
            difference = difference or (expected[i].code xor actual[i].code)
        }
        return difference == 0
    }

    /**
     * A trust manager that accepts exactly one certificate and nothing else.
     * An empty chain, a different certificate, or an expired pin all end the
     * handshake.
     */
    private class PinnedTrustManager(private val pin: String) : X509TrustManager {
        override fun checkClientTrusted(chain: Array<out X509Certificate>?, authType: String?) {
            throw CertificateException("This app is never a TLS server")
        }

        override fun checkServerTrusted(chain: Array<out X509Certificate>?, authType: String?) {
            val leaf = chain?.firstOrNull()
                ?: throw CertificateException("The server sent no certificate")
            if (!matches(leaf, pin)) {
                throw CertificateException(
                    "The certificate of the device has changed. Pair again only if you " +
                        "changed it yourself."
                )
            }
        }

        override fun getAcceptedIssuers(): Array<X509Certificate> = emptyArray()
    }

    /**
     * Used only while pairing, to read the certificate the device offers so its
     * fingerprint can be put in front of the user. Nothing that matters is sent
     * over a connection built with this.
     */
    private class ProbeTrustManager : X509TrustManager {
        override fun checkClientTrusted(chain: Array<out X509Certificate>?, authType: String?) {}

        override fun checkServerTrusted(chain: Array<out X509Certificate>?, authType: String?) {}

        override fun getAcceptedIssuers(): Array<X509Certificate> = emptyArray()
    }

    fun socketFactoryFor(pin: String): SSLSocketFactory = contextWith(PinnedTrustManager(pin)).socketFactory

    private fun contextWith(manager: TrustManager): SSLContext =
        SSLContext.getInstance("TLS").apply { init(null, arrayOf(manager), null) }

    /**
     * The certificate names the device by its .local hostname, so connecting to
     * it by address would fail the usual name check. That check exists to tie a
     * certificate to a name, and the pin ties it to one exact certificate
     * instead, which is the stronger of the two. It is only ever used together
     * with a pinned socket factory.
     */
    fun pinnedHostnameVerifier(): HostnameVerifier =
        HostnameVerifier { _: String?, _: SSLSession? -> true }

    /**
     * Opens a bare TLS connection to read the certificate, without sending a
     * request. Throws if the device cannot be reached.
     */
    @Throws(Exception::class)
    fun probeCertificate(host: String, port: Int, timeoutMillis: Int = 8000): X509Certificate {
        val factory = contextWith(ProbeTrustManager()).socketFactory
        Socket().use { plain ->
            plain.connect(InetSocketAddress(host, port), timeoutMillis)
            plain.soTimeout = timeoutMillis
            (factory.createSocket(plain, host, port, true) as SSLSocket).use { secure ->
                secure.startHandshake()
                val chain = secure.session.peerCertificates
                val leaf = chain.firstOrNull() as? X509Certificate
                    ?: throw CertificateException("The device sent no usable certificate")
                return leaf
            }
        }
    }
}
