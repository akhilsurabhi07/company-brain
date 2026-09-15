# Decoupled Frontend Specification — Module 6B

## 1. Interface Boundary
The EXL frontend is built with high-performance vanilla HTML, CSS, and JS to eliminate heavy framework overhead and ensure instant page load speeds (<50ms DOM interactive time).

## 2. File Organization
```text
frontend/
├── index.html        # Main Single Page Application (SPA) container
├── theme.css         # Royal purple / midnight black CSS design system
└── app.js            # Async API controller & view state management
```

## 3. Communication Protocols
- **API Endpoint Format**: Standard JSON over HTTP POST/GET.
- **Error Handling**: Graceful client-side fallback to grounded engine mock responses during network disconnection or API rate limits.
