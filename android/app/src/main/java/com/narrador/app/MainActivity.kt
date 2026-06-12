package com.narrador.app

import android.content.Intent
import android.net.Uri
import android.os.Bundle
import androidx.appcompat.app.AppCompatActivity
import androidx.fragment.app.commit
import com.narrador.app.books.BooksFragment
import com.narrador.app.browser.BrowserFragment
import com.narrador.app.databinding.ActivityMainBinding

class MainActivity : AppCompatActivity() {

    private lateinit var binding: ActivityMainBinding
    private var browserFragment: BrowserFragment? = null
    private var booksFragment: BooksFragment? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityMainBinding.inflate(layoutInflater)
        setContentView(binding.root)

        if (savedInstanceState == null) {
            browserFragment = BrowserFragment.newInstance()
            booksFragment = BooksFragment.newInstance()
            supportFragmentManager.commit {
                add(R.id.fragment_container, browserFragment!!, TAG_BROWSER)
                add(R.id.fragment_container, booksFragment!!, TAG_BOOKS)
                hide(booksFragment!!)
            }
        } else {
            browserFragment = supportFragmentManager.findFragmentByTag(TAG_BROWSER) as? BrowserFragment
            booksFragment = supportFragmentManager.findFragmentByTag(TAG_BOOKS) as? BooksFragment
        }

        binding.bottomNav.setOnItemSelectedListener { item ->
            when (item.itemId) {
                R.id.nav_browser -> showBrowser()
                R.id.nav_books -> showBooks()
                else -> false
            }
        }

        handleIntent(intent)
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        handleIntent(intent)
    }

    private fun handleIntent(intent: Intent?) {
        val data: Uri = intent?.data ?: return
        val scheme = data.scheme?.lowercase()
        when {
            scheme == "http" || scheme == "https" -> {
                binding.bottomNav.selectedItemId = R.id.nav_browser
                showBrowser()
                browserFragment?.loadExternalUrl(data.toString())
            }
            intent?.action == Intent.ACTION_VIEW -> {
                binding.bottomNav.selectedItemId = R.id.nav_books
                showBooks()
                booksFragment?.openDocument(data)
            }
        }
    }

    private fun showBrowser(): Boolean {
        val books = booksFragment ?: return false
        val browser = browserFragment ?: return false
        supportFragmentManager.commit {
            show(browser)
            hide(books)
        }
        return true
    }

    private fun showBooks(): Boolean {
        val books = booksFragment ?: return false
        val browser = browserFragment ?: return false
        supportFragmentManager.commit {
            show(books)
            hide(browser)
        }
        return true
    }

    companion object {
        private const val TAG_BROWSER = "browser"
        private const val TAG_BOOKS = "books"
    }
}
