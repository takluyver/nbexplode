Explode a notebook into a directory of files, and recombine it to a .ipynb

Exploded notebooks have some advantages in version control: it should be easier
to merge changes in this form. They are more unwieldy in many ways, though.

Usage::

    python3 nbexplode.py Foo.ipynb
    python3 nbexplode.py -r Foo.ipynb.exploded
