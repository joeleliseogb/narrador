package com.narrador.app.books

import java.io.InputStream
import java.util.zip.ZipEntry
import java.util.zip.ZipInputStream

/** Lee EPUB (ZIP + OPF) sin librerías externas. */
object EpubSimpleReader {

    fun readSections(stream: InputStream, docName: String): List<BookSection> {
        val entries = readZipEntries(stream)
        val opfPath = findOpfPath(entries)
            ?: throw IllegalArgumentException("EPUB inválido: falta content.opf")
        val opf = entries[opfPath] ?: throw IllegalArgumentException("No se pudo leer OPF")
        val manifest = parseManifest(opf)
        val spineHrefs = parseSpine(opf, manifest)
        val baseDir = opfPath.substringBeforeLast('/', "")

        val sections = mutableListOf<BookSection>()
        spineHrefs.forEachIndexed { index, href ->
            val path = resolvePath(baseDir, href)
            val html = entries[path] ?: entries[href] ?: return@forEachIndexed
            val text = htmlToText(html)
            if (text.length > 40) {
                sections.add(BookSection("$docName · ${index + 1}", text))
            }
        }

        if (sections.isEmpty()) {
            val fallback = entries.filterKeys { it.endsWith(".xhtml") || it.endsWith(".html") }
                .values
                .joinToString("\n\n") { htmlToText(it) }
                .trim()
            if (fallback.isBlank()) throw IllegalArgumentException("EPUB sin texto legible")
            return listOf(BookSection(docName, fallback))
        }
        return sections
    }

    private fun readZipEntries(stream: InputStream): Map<String, String> {
        val map = linkedMapOf<String, String>()
        ZipInputStream(stream).use { zip ->
            var entry: ZipEntry? = zip.nextEntry
            while (entry != null) {
                if (!entry.isDirectory) {
                    val bytes = zip.readBytes()
                    map[entry.name] = bytes.toString(Charsets.UTF_8)
                }
                entry = zip.nextEntry
            }
        }
        return map
    }

    private fun findOpfPath(entries: Map<String, String>): String? {
        val container = entries["META-INF/container.xml"] ?: return null
        val match = Regex("full-path=\"([^\"]+)\"").find(container) ?: return null
        return match.groupValues[1]
    }

    private fun parseManifest(opf: String): Map<String, String> {
        val map = mutableMapOf<String, String>()
        Regex("<item[^>]+id=\"([^\"]+)\"[^>]+href=\"([^\"]+)\"")
            .findAll(opf)
            .forEach { m -> map[m.groupValues[1]] = m.groupValues[2] }
        Regex("<item[^>]+href=\"([^\"]+)\"[^>]+id=\"([^\"]+)\"")
            .findAll(opf)
            .forEach { m -> map[m.groupValues[2]] = m.groupValues[1] }
        return map
    }

    private fun parseSpine(opf: String, manifest: Map<String, String>): List<String> {
        val ids = Regex("<itemref[^>]+idref=\"([^\"]+)\"")
            .findAll(opf)
            .map { it.groupValues[1] }
            .toList()
        return ids.mapNotNull { manifest[it] }
    }

    private fun resolvePath(baseDir: String, href: String): String {
        if (href.startsWith("/")) return href.removePrefix("/")
        return if (baseDir.isEmpty()) href else "$baseDir/$href"
    }

    private fun htmlToText(html: String): String {
        return html
            .replace(Regex("(?is)<(script|style)[^>]*>.*?</\\1>"), " ")
            .replace(Regex("<[^>]+>"), " ")
            .replace(Regex("\\s+"), " ")
            .trim()
    }
}
