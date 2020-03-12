from setuptools import setup, find_packages

if __name__ == "__main__":
    setup(
        name='inliner',
        version='0.3.12',
        description='Human-readable inlining of Python code',
        url='http://github.com/willcrichton/inliner',
        author='Will Crichton',
        author_email='wcrichto@cs.stanford.edu',
        license='Apache 2.0',
        packages=find_packages(),
        install_requires=[
            'astor', 'iterextras', 'asttokens',
            'ast_tools @ https://github.com/leonardt/ast_tools/tarball/master#egg=ast_tools-0.0.14'
        ],
        data_files=[('share/jupyter/nbextensions/inliner', [
            'inliner_jupyter/dist/notebook.js',
            'inliner_jupyter/dist/notebook.js.map',
        ]), ('etc/jupyter/nbconfig/notebook.d',
             ['inliner_jupyter/inliner.json'])],
        setup_requires=['pytest-runner'],
        tests_require=['pytest', 'seaborn', 'pandas', 'numpy'],
        zip_safe=False)
