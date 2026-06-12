package com.narrador.app.books

import android.app.Activity
import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.provider.OpenableColumns
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.fragment.app.Fragment
import androidx.lifecycle.lifecycleScope
import com.narrador.app.NarradorApp
import com.narrador.app.R
import com.narrador.app.databinding.FragmentBooksBinding
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

class BooksFragment : Fragment() {

    private var _binding: FragmentBooksBinding? = null
    private val binding get() = _binding!!

    private var sections: List<BookSection> = emptyList()
    private var sectionIndex = 0
    private var readJob: Job? = null
    private var paused = false
    private var fileUri: Uri? = null
    private var fileName: String = ""

    private val pickDocument = registerForActivityResult(
        ActivityResultContracts.OpenDocument()
    ) { uri ->
        if (uri != null) loadDocument(uri)
    }

    override fun onCreateView(
        inflater: LayoutInflater,
        container: ViewGroup?,
        savedInstanceState: Bundle?,
    ): View {
        _binding = FragmentBooksBinding.inflate(inflater, container, false)
        return binding.root
    }

    override fun onViewCreated(view: View, savedInstanceState: Bundle?) {
        super.onViewCreated(view, savedInstanceState)

        binding.btnPickFile.setOnClickListener {
            pickDocument.launch(
                arrayOf(
                    "text/*",
                    "application/pdf",
                    "application/epub+zip",
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    "application/msword",
                )
            )
        }

        binding.btnPlay.setOnClickListener {
            paused = false
            if (sections.isEmpty()) {
                Toast.makeText(requireContext(), R.string.books_no_file, Toast.LENGTH_SHORT).show()
                return@setOnClickListener
            }
            startNarration()
        }

        binding.btnPause.setOnClickListener {
            paused = true
            (requireActivity().application as NarradorApp).tts.stop()
        }

        binding.btnStop.setOnClickListener {
            paused = true
            readJob?.cancel()
            readJob = null
            sectionIndex = 0
            (requireActivity().application as NarradorApp).tts.stop()
        }

        binding.speedSlider.addOnChangeListener { _, value, _ ->
            (requireActivity().application as NarradorApp).tts.rate = value
        }
    }

    fun openDocument(uri: Uri) {
        loadDocument(uri)
    }

    private fun loadDocument(uri: Uri) {
        val ctx = requireContext()
        fileUri = uri
        try {
            ctx.contentResolver.takePersistableUriPermission(
                uri,
                Intent.FLAG_GRANT_READ_URI_PERMISSION
            )
        } catch (_: SecurityException) {
            /* picker one-shot */
        }

        fileName = queryDisplayName(uri) ?: "documento"
        binding.fileLabel.text = fileName
        binding.bookPreview.text = getString(R.string.books_pick) + "…"

        viewLifecycleOwner.lifecycleScope.launch {
            val loaded = withContext(Dispatchers.IO) {
                runCatching {
                    DocumentExtractor.extract(ctx, uri, fileName)
                }
            }
            loaded.onSuccess { list ->
                sections = list
                sectionIndex = 0
                val firstText = list.firstOrNull()?.text.orEmpty()
                val preview = firstText.take(4000)
                binding.bookPreview.text = if (preview.length < firstText.length) {
                    "$preview…"
                } else {
                    preview
                }
                binding.fileLabel.text = "$fileName (${list.size} sección/es)"
            }.onFailure { err ->
                sections = emptyList()
                binding.bookPreview.text = err.message ?: err.toString()
                Toast.makeText(ctx, err.message, Toast.LENGTH_LONG).show()
            }
        }
    }

    private fun startNarration() {
        readJob?.cancel()
        val app = requireActivity().application as NarradorApp
        app.tts.rate = binding.speedSlider.value
        app.tts.langTag = "es-ES"

        readJob = viewLifecycleOwner.lifecycleScope.launch {
            while (isActive && sectionIndex < sections.size) {
                if (paused) break
                val section = sections[sectionIndex]
                val chunks = section.text.split(Regex("(?<=[.!?])\\s+"))
                    .map { it.trim() }
                    .filter { it.length > 2 }

                for (chunk in chunks) {
                    if (!isActive || paused) return@launch
                    val done = kotlinx.coroutines.CompletableDeferred<Unit>()
                    withContext(Dispatchers.Main) {
                        app.tts.speak(chunk) { done.complete(Unit) }
                    }
                    done.await()
                    kotlinx.coroutines.delay(120)
                }
                sectionIndex++
            }
        }
    }

    private fun queryDisplayName(uri: Uri): String? {
        val cursor = requireContext().contentResolver.query(uri, null, null, null, null)
        cursor?.use {
            if (it.moveToFirst()) {
                val idx = it.getColumnIndex(OpenableColumns.DISPLAY_NAME)
                if (idx >= 0) return it.getString(idx)
            }
        }
        return uri.lastPathSegment
    }

    override fun onDestroyView() {
        readJob?.cancel()
        _binding = null
        super.onDestroyView()
    }

    companion object {
        fun newInstance(): BooksFragment = BooksFragment()
    }
}
