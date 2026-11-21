"""Cestino della libreria: visibilità distinta dagli usi conservati nei cut."""
from app.store import StoreError


class LibraryOperations:
    def _library_trashed(self, db, project_id):
        return {(row['kind'], row['reference_id']) for row in db.execute(
            'SELECT kind,reference_id FROM library_trash WHERE project_id=?', (str(project_id),))}

    def _check_library_reuse(self, db, project_id, kind, reference_id):
        if (kind, str(reference_id)) in self._library_trashed(db, project_id):
            label = 'Il Subject' if kind == 'unit' else 'L’immagine'
            raise StoreError('library_trashed', label + ' è nel cestino della libreria. Ripristina il riferimento prima del riuso.', 409)

    def trash_library(self, project_id, kind, reference_id, command):
        def action(db):
            from app.repository import now
            project = self._entity(db, 'projects', project_id, command.expected_revision)
            table = {'picture': 'project_references', 'unit': 'project_units'}[kind]
            row = db.execute(f'SELECT * FROM {table} WHERE id=? AND project_id=?',
                             (str(reference_id), str(project_id))).fetchone()
            if row is None:
                raise StoreError('not_found', 'Riferimento non trovato nella libreria del progetto.', 404)
            if row['revision'] != command.expected_reference_revision:
                raise StoreError('reference_conflict', 'Il riferimento è cambiato. Ricarica la libreria prima di modificarne il cestino.', 409)
            current = (kind, str(reference_id)) in self._library_trashed(db, project_id)
            revision = project['revision']
            if current != command.trashed:
                if command.trashed:
                    db.execute('INSERT INTO library_trash VALUES (?,?,?,?)',
                               (str(project_id), kind, str(reference_id), now()))
                    if kind == 'unit':
                        db.execute('UPDATE project_units SET retained=1 WHERE id=?', (str(reference_id),))
                else:
                    db.execute('DELETE FROM library_trash WHERE project_id=? AND kind=? AND reference_id=?',
                               (str(project_id), kind, str(reference_id)))
                db.execute('UPDATE projects SET revision=revision+1,updated_at=? WHERE id=?', (now(), str(project_id)))
                revision += 1
            return dict(revision=revision, kind=kind, reference_id=str(reference_id), trashed=command.trashed)
        return self._entity_command(f'library_trash:{kind}:{reference_id}', project_id, command, action)
