import base64
import pathlib
import json
import re
import shutil
from uuid import uuid4

from IPython import nbformat as nbf

_mime_to_ext = {
    'text/plain': '.txt',
    'text/html': '.html',
    'text/latex': '.tex',
    'image/png': '.png',
    'image/jpeg': '.jpg',
}

def _is_binary(mime):
    return mime.startswith(('image/', 'application/', 'audio'))

def explode_output(output, cell_dir, i):
    optype = output.pop('output_type')
    if optype == 'stream':
        with (cell_dir / ('output%d.txt' % i)).open(
                     'w', encoding='utf-8') as f:
            f.write(output.text)

        return output.name

    elif optype == 'error':
        with (cell_dir / ('error%d.json' % i)).open('w') as f:
            json.dump(output, f, indent=2, sort_keys=True)
        return 'error'

    elif optype in {'execute_result', 'display_data'}:
        with (cell_dir / ('output%d-metadata.json' % i)).open(
                     'w', encoding='utf-8') as f:
            json.dump(output.metadata, f, indent=2, sort_keys=True)
        mimetypes = ", ".join(sorted(output.data))

        for mimetype, data in output.data.items():
            file = cell_dir / 'output{}{}'.format(i, _mime_to_ext[mimetype])
            if _is_binary(mimetype):
                with file.open('wb') as f:
                    f.write(base64.b64decode(data.encode('ascii')))
            else:
                with file.open('w', encoding='utf-8') as f:
                    f.write(data)

        if optype == 'execute_result':
            return mimetypes + (' (%d)' % output.execution_count)
        else:
            return mimetypes

def explode(nbnode, directory):
    directory = pathlib.Path(directory)
    with (directory / 'metadata.json').open('w') as f:
        json.dump(nbnode.metadata, f, indent=2, sort_keys=True)

    cell_ids = []
    for cell in nbnode.cells:
        if 'nbexplode_cell_id' in cell.metadata:
            cell_id = cell.metadata.pop('nbexplode_cell_id')
        else:
            cell_id = str(uuid4())

        cell_ids.append(cell_id)

        cell_dir = directory / cell_id
        cell_dir.mkdir()

        if cell.cell_type == 'markdown':
            source_file = 'source.md'
        elif cell.cell_type == 'raw':
            source_file = 'source.txt'
        else:
            # Code cell
            source_file = 'source' + nbnode.metadata.language_info.file_extension

        with (cell_dir / source_file).open('w', encoding='utf-8') as f:
            f.write(cell.source)

        if cell.metadata:
            with (cell_dir / 'metadata.json').open('w') as f:
                json.dump(cell.metadata, f, indent=2, sort_keys=True)

        if not cell.get('outputs'):
            continue

        output_counter = 0
        outputs_seq = []
        for output in cell.outputs:
            output_counter += 1
            outputs_seq.append(explode_output(output, cell_dir, output_counter))

        with (cell_dir / 'outputs_sequence').open('w') as f:
            for l in outputs_seq:
                f.write(l + '\n')


    with (directory / 'cells_sequence').open('w') as f:
        for c in cell_ids:
            f.write(c + '\n')

_exec_result_re = re.compile(r'\((\d+)\)$')

def recombine_output(cell_dir, i, info):
    if info in {'stdout', 'stderr'}:
        with (cell_dir / ('output%d.txt' % i)).open() as f:
            return nbf.v4.new_output('stream', name=info, text=f.read())

    elif info == 'error':
        with (cell_dir / ('error%d.json' % i)).open() as f:
            err_data = json.load(f)
        return nbf.v4.new_output('error', **err_data)

    else:
        m = _exec_result_re.search(info)
        if m:
            info = info[:-(len(m.group(0))+1)]
            op = nbf.v4.new_output('execute_result', execution_count=int(m.group(1)))
        else:
            op = nbf.v4.new_output('display_data')

        mimebundle = {}
        for mimetype in info.split(", "):
            file = "output{}{}".format(i, _mime_to_ext[mimetype])
            if _is_binary(mimetype):
                with (cell_dir / file).open('rb') as f:
                    mimebundle[mimetype] = base64.b64encode(f.read()).decode('ascii')

            else:
                with (cell_dir / file).open() as f:
                    mimebundle[mimetype] = f.read()

        op.data = nbf.from_dict(mimebundle)

        metadata_file = cell_dir / "output{}-metadata.json".format(i)
        if metadata_file.exists():
            with metadata_file.open() as f:
                op.metadata = nbf.from_dict(json.load(f))

        return op

def recombine(directory):
    directory = pathlib.Path(directory)
    with (directory / 'metadata.json').open() as f:
        metadata = json.load(f)

    nb = nbf.v4.new_notebook(metadata=metadata)

    with (directory / 'cells_sequence').open() as f:
        cells_sequence = f.read().splitlines()

    for cell_id in cells_sequence:
        cell_dir = directory / cell_id

        source_file = list(cell_dir.glob('source.*'))[0]
        if source_file.suffix == '.md':
            with source_file.open() as f:
                cell = nbf.v4.new_markdown_cell(f.read())
        elif source_file.suffix == '.txt':
            with source_file.open() as f:
                cell = nbf.NotebookNode(cell_type='raw',
                            source=f.read(),
                            metadata=nbf.NotebookNode())
        else:
            with source_file.open() as f:
                cell = nbf.v4.new_code_cell(f.read())

        nb.cells.append(cell)

        if (cell_dir / 'metadata.json').exists():
            with (cell_dir / 'metadata.json').open() as f:
                cell.metadata = nbf.from_dict(json.load(f))

        cell.metadata['nbexplode_cell_id'] = cell_id

        if not (cell_dir / 'outputs_sequence').exists():
            continue

        with (cell_dir / 'outputs_sequence').open() as f:
            outputs_seq = f.read().splitlines()

        cell.outputs = [recombine_output(cell_dir, i, info)
                        for (i, info) in enumerate(outputs_seq, start=1)]

    return nb

def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('-r', '--recombine', action='store_true')
    ap.add_argument('file')
    args = ap.parse_args(argv)

    if args.recombine:
        assert args.file.endswith('.ipynb.exploded')
        nb = recombine(args.file)
        nbf.write(nb, args.file[:-len('.exploded')])
    else:
        assert args.file.endswith('.ipynb')
        nb = nbf.read(args.file, as_version=4)
        directory = pathlib.Path(args.file + '.exploded')
        if directory.is_dir():
            shutil.rmtree(str(directory))
        directory.mkdir()
        explode(nb, directory)

if __name__ == '__main__':
    main()