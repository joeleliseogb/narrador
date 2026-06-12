package com.narrador.app.browser

import android.annotation.SuppressLint
import android.graphics.Bitmap
import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.webkit.CookieManager
import android.webkit.WebChromeClient
import android.webkit.WebResourceRequest
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.core.view.isVisible
import androidx.fragment.app.Fragment
import com.narrador.app.NarradorApp
import com.narrador.app.R
import com.narrador.app.databinding.FragmentBrowserBinding

class BrowserFragment : Fragment() {

    private var _binding: FragmentBrowserBinding? = null
    private val binding get() = _binding!!
    private var narrationEnabled = true
    private var narradorScript: String? = null

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreateView(
        inflater: LayoutInflater,
        container: ViewGroup?,
        savedInstanceState: Bundle?,
    ): View {
        _binding = FragmentBrowserBinding.inflate(inflater, container, false)
        return binding.root
    }

    override fun onViewCreated(view: View, savedInstanceState: Bundle?) {
        super.onViewCreated(view, savedInstanceState)
        narradorScript = requireContext().assets.open("narrador-youtube.js")
            .bufferedReader()
            .use { it.readText() }

        val app = requireActivity().application as NarradorApp

        binding.switchNarration.setOnCheckedChangeListener { _, checked ->
            narrationEnabled = checked
            binding.switchNarration.text = getString(
                if (checked) R.string.narration_on else R.string.narration_off
            )
            injectNarrador(binding.webview.url)
        }

        binding.btnGo.setOnClickListener { loadUrl(binding.urlInput.text?.toString()) }

        val wv = binding.webview
        CookieManager.getInstance().setAcceptCookie(true)
        CookieManager.getInstance().setAcceptThirdPartyCookies(wv, true)

        wv.settings.apply {
            javaScriptEnabled = true
            domStorageEnabled = true
            databaseEnabled = true
            mediaPlaybackRequiresUserGesture = false
            useWideViewPort = true
            loadWithOverviewMode = true
            builtInZoomControls = true
            displayZoomControls = false
            mixedContentMode = WebSettings.MIXED_CONTENT_COMPATIBILITY_MODE
            userAgentString = DESKTOP_CHROME_UA
        }

        wv.addJavascriptInterface(
            NarradorJsInterface(app, { wv }, { narrationEnabled }),
            "NarradorAndroid"
        )

        wv.webChromeClient = object : WebChromeClient() {
            override fun onProgressChanged(view: WebView?, newProgress: Int) {
                binding.browserProgress.isVisible = newProgress in 1..99
                if (newProgress >= 100) binding.browserProgress.isVisible = false
            }
        }

        wv.webViewClient = object : WebViewClient() {
            override fun shouldOverrideUrlLoading(
                view: WebView,
                request: WebResourceRequest,
            ): Boolean {
                val url = request.url.toString()
                if (url.startsWith("http://") || url.startsWith("https://")) {
                    binding.urlInput.setText(url)
                    return false
                }
                return true
            }

            override fun onPageFinished(view: WebView, url: String) {
                binding.urlInput.setText(url)
                injectNarrador(url)
            }
        }

        val start = arguments?.getString(ARG_URL)
            ?: "https://m.youtube.com"
        binding.urlInput.setText(start)
        wv.loadUrl(start)
    }

    fun loadExternalUrl(url: String?) {
        if (url.isNullOrBlank()) return
        _binding?.urlInput?.setText(url)
        loadUrl(url)
    }

    private fun loadUrl(raw: String?) {
        var url = raw?.trim().orEmpty()
        if (url.isEmpty()) return
        if (!url.startsWith("http")) url = "https://$url"
        binding.webview.loadUrl(url)
    }

    private fun injectNarrador(url: String?) {
        if (url.isNullOrBlank()) return
        val host = runCatching { android.net.Uri.parse(url).host?.lowercase() }.getOrNull()
        if (host == null || !host.contains("youtube")) return
        val script = narradorScript ?: return
        binding.webview.evaluateJavascript(script, null)
    }

    override fun onPause() {
        super.onPause()
        binding.webview.onPause()
        (requireActivity().application as NarradorApp).tts.stop()
    }

    override fun onResume() {
        super.onResume()
        binding.webview.onResume()
    }

    override fun onDestroyView() {
        binding.webview.destroy()
        _binding = null
        super.onDestroyView()
    }

    companion object {
        const val ARG_URL = "url"
        private const val DESKTOP_CHROME_UA =
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

        fun newInstance(url: String? = null): BrowserFragment {
            return BrowserFragment().apply {
                arguments = Bundle().apply { putString(ARG_URL, url) }
            }
        }
    }
}
