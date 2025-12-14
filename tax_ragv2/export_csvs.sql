\copy (SELECT * FROM documents ORDER BY doc_id) TO 'documents.csv' CSV HEADER;
\copy (SELECT section_id, doc_id, level, path, heading, section_number, parent_section_id FROM sections ORDER BY path) TO 'sections.csv' CSV HEADER;
\copy (SELECT chunk_id, doc_id, section_id, chunk_index, token_count, section_path, citations, LENGTH(content) AS content_length, content FROM chunks ORDER BY section_path, chunk_index) TO 'chunks.csv' CSV HEADER;
