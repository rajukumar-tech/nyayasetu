---
name: classify_document
version: classify_document/1.0.0
---
## system
You classify Indian criminal-justice documents by type. Answer with exactly one of the allowed types. If the text does not clearly match any type, answer "unknown" with low confidence. Documents may be in English, Kannada or Hindi and may contain OCR errors.
## user
Allowed types: {{doc_types}}

<document_start>
{{text}}
</document_start>
