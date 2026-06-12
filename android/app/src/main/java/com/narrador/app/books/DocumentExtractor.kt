package com.narrador.app.books

import android.content.Context
import android.net.Uri
import com.tom_roush.pdfbox.android.PDFBoxResourceLoader
import com.tom_roush.pdfbox.pdmodel.PDDocument
import com.tom_roush.pdfbox.text.PDFTextStripper
import org.apache.poi.xwpf.usermodel.XWPFDocument
import java.io.BufferedReader
import java.io.InputStreamReader
import java.util.zip.ZipInputStream

data class BookSection(val title: String, val text: String)

object DocumentExtractor {

    fun extract(context: Context, uri: Uri, displayName: String): List<BookSection> {
        PDFBoxResourceLoader.init(context.applicationContext)
        val name = displayName.lowercase()
        context.contentResolver.openInputStream(uri).use { stream ->
            requireNotNull(stream) { "No se pudo abrir el archivo" }
            return when {
                name.endsWith(".txt") -> listOf(BookSection(displayName, readTxt(stream)))
                name.endsWith(".pdf") -> sectionsFromPlain(readPdf(stream), displayName)
                name.endsWith(".epub") -> readEpub(stream, displayName)
                name.endsWith(".docx") || name.endsWith(".docm") -> sectionsFromPlain(readDocx(stream), displayName)
                name.endsWith(".doc") -> sectionsFromPlain(readDocx(stream), displayName)
                else -> throw IllegalArgumentException("Formato no soportado: $displayName")
            }
        }
    }

    private fun readTxt(stream: java.io.InputStream): String {
        return BufferedReader(InputStreamReader(stream, Charsets.UTF_8)).use { it.readText() }.trim()
    }

    private fun readPdf(stream: java.io.InputStream): String {
        PDDocument.load(stream).use { doc ->
            val stripper = PDFTextStripper()
            return stripper.getText(doc).trim()
        }
    }

    private fun readEpub(stream: java.io.InputStream, docName: String): List<BookSection> {
        return EpubSimpleReader.readSections(stream, docName)
    }

    private fun readDocx(stream: java.io.InputStream): String {
        return try {
            XWPFDocument(stream).use { doc ->
                buildString {
                    doc.paragraphs.forEach { p ->
                        val t = p.text?.trim().orEmpty()
                        if (t.isNotEmpty()) {
                            append(t)
                            append("\n\n")
                        }
                    }
                    doc.tables.forEach { table ->
                        table.rows.forEach { row ->
                            val cells = row.tableCells.map { it.text.trim() }.filter { it.isNotEmpty() }
                            if (cells.isNotEmpty()) {
                                append(cells.joinToString(" — "))
                                append("\n")
                            }
                        }
                    }
                }.trim()
            }
        } catch (_: Exception) {
            readDocxAsZip(stream)
        }
    }

    private fun readDocxAsZip(stream: java.io.InputStream): String {
        val bytes = stream.readBytes()
        ZipInputStream(bytes.inputStream()).use { zip ->
            var entry = zip.nextEntry
            val sb = StringBuilder()
            while (entry != null) {
                if (entry.name == "word/document.xml") {
                    val xml = zip.readBytes().toString(Charsets.UTF_8)
                    val text = xml.replace(Regex("<w:tab[^/]*/>"), "\t")
                        .replace(Regex("</w:p>"), "\n")
                        .replace(Regex("<[^>]+>"), "")
                        .replace(Regex("\\s+"), " ")
                        .trim()
                    sb.append(text)
                    break
                }
                entry = zip.nextEntry
            }
            return sb.toString().ifBlank { throw IllegalArgumentException("DOCX no legible") }
        }
    }

    private fun sectionsFromPlain(text: String, docName: String): List<BookSection> {
        val blocks = text.split(Regex("\n\\s*\n+")).map { it.trim() }.filter { it.isNotEmpty() }
        if (blocks.isEmpty()) return emptyList()
        if (blocks.size == 1) return listOf(BookSection(docName, blocks[0]))
        return blocks.mapIndexed { i, block ->
            BookSection("$docName · ${i + 1}", block)
        }
    }
}
