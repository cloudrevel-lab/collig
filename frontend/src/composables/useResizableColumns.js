// composable/useResizableColumns.js
import { ref, onMounted, onBeforeUnmount } from 'vue'

export function useResizableColumns(tableId) {
  const colWidths = ref({})

  // Load saved widths from localStorage
  function loadWidths(defaultWidths = {}) {
    try {
      const saved = localStorage.getItem(`collig-col-widths-${tableId}`)
      if (saved) colWidths.value = JSON.parse(saved)
    } catch {}
  }

  // Save widths to localStorage
  function saveWidths() {
    try {
      localStorage.setItem(`collig-col-widths-${tableId}`, JSON.stringify(colWidths.value))
    } catch {}
  }

  // Apply width to a header and all cells in that column
  function applyWidth(index, width) {
    colWidths.value[index] = width
    saveWidths()

    const table = document.querySelector(`[data-table-id="${tableId}"]`)
    if (!table) return

    // Apply to header
    const headers = table.querySelectorAll('thead th')
    if (headers[index]) {
      headers[index].style.width = width + 'px'
      headers[index].style.minWidth = width + 'px'
      headers[index].style.maxWidth = width + 'px'
      // Also set via setAttribute for better browser support
      headers[index].setAttribute('style', `width: ${width}px; min-width: ${width}px; max-width: ${width}px;`)
    }

    // Apply to body cells
    const rows = table.querySelectorAll('tbody tr')
    rows.forEach(row => {
      const cells = row.querySelectorAll('td')
      if (cells[index]) {
        cells[index].style.width = width + 'px'
        cells[index].style.minWidth = width + 'px'
        cells[index].style.maxWidth = width + 'px'
        cells[index].setAttribute('style', `width: ${width}px; min-width: ${width}px; max-width: ${width}px;`)
      }
    })
  }

  // Set up drag handlers on header resizers
  function initResizers(defaultWidths = {}) {
    const table = document.querySelector(`[data-table-id="${tableId}"]`)
    if (!table) return

    // First, clear any inline styles from existing cells
    const allCells = table.querySelectorAll('td')
    allCells.forEach(cell => cell.removeAttribute('style'))

    const headers = table.querySelectorAll('thead th')
    headers.forEach((th, index) => {
      // Skip last column (actions) if it has no resizer needed
      if (index === headers.length - 1) return

      // Create resizer handle if not exists
      let resizer = th.querySelector('.col-resizer')
      if (!resizer) {
        resizer = document.createElement('div')
        resizer.className = 'col-resizer'
        th.appendChild(resizer)

        let startX, startW

        const onMouseDown = (e) => {
          e.preventDefault()
          e.stopPropagation()
          startX = e.clientX
          startW = th.offsetWidth

          const onMouseMove = (e2) => {
            const newW = Math.max(60, startW + (e2.clientX - startX))
            applyWidth(index, newW)
          }

          const onMouseUp = () => {
            document.removeEventListener('mousemove', onMouseMove)
            document.removeEventListener('mouseup', onMouseUp)
          }

          document.addEventListener('mousemove', onMouseMove)
          document.addEventListener('mouseup', onMouseUp)
        }

        resizer.addEventListener('mousedown', onMouseDown)
      }
    })

    // Apply default widths if none saved
    Object.entries(defaultWidths).forEach(([idx, w]) => {
      if (colWidths.value[idx] === undefined) {
        applyWidth(parseInt(idx), w)
      }
    })
  }

  onMounted(() => {
    loadWidths()
    // Wait for table to render
    setTimeout(() => {
      initResizers()
      // Re-apply saved widths
      Object.entries(colWidths.value).forEach(([idx, w]) => {
        applyWidth(parseInt(idx), w)
      })
    }, 200)
  })

  return { colWidths, initResizers, applyWidth }
}
