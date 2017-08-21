# PyOrbital
Distribute private resources, such as machine learning models, through AWS.
 
## Motivation

[Sputnik](https://github.com/pombredanne/sputnik/tree/master/sputnik) is a great library that 
manages data packages for another library, e.g. trained models for a machine learning library. 
However, Sputnik assumes packages will be hosted behind a webserver, which creates a fair bit of
scaffolding work. We would like data packages to live on Amazon S3 instead. This library adds a 
single function, `patch_sputnik`, which should be called before uploading or downloading a 
Sputnik-managed resource.

## Usage

Please refer to Sputnik"s README for full details on how to structure a package so it can be managed
by Sputnik. Essentially, the process is:

1. Create a resource (on machine A)
1. Publish resource (on machine A)
1. Install resource (on machine B)

A full example can be found in `orbital/test/test_orbital.py`.

### Creation

Write your data resource as follows:

```
.
└── sputnik_sample
    ├── data
    │   └── model.pkl
    └── package.json
```

Here, `model.pkl` is the model that we want to distribute, and `package.json` is a manifest containing
metadata about the model, e.g.

```json
{
    "name": "orbital_test_model",
    "description": "This is a demo model, but it is still awesome.",
    "include": [["data", "*"]],
    "version": "2.0.0",
    "license": "Proprietary",
    "compatibility": {
        "my_library": ">=1.1.1"
    }
}

```

Then build the package for distribution:

```python
import sputnik

package = sputnik.build("sputnik_sample")
```

### Publishing

```python
from orbital import patch_sputnik
import sputnik

patch_sputnik()
sputnik.upload("myapp", "1.0.0", package.path)
```

This uploads the package to an S3 bucket. This can be public or private.

### Installation
```python
from orbital import patch_sputnik
import sputnik

patch_sputnik()
sputnik.install("my_library", "1.0.0", "orbital_test_model==2.0.0")
```

This downloads and unpacks the required model version into a local directory.

### Use installed model

```
package = sputnik.package("my_library", "1.1.3.", "orbital_test_model==2.0.0")
path_to_load = package.file_path(model_file_name)
```

Then load the model as usual, e.g. pickle.

## S3 setup

Orbital does not create the S3 bucket where resources will be stored. You have to do that manually. 
The name of the bucket has to be provided as an environment variable to the upload script, e.g.

```bash
BUCKET="my_private_s3_bucket" python upload_all_models.py
```


To upload to a private bucket, you also need to create an AWS IAM use and give them R/W access to the
bucket. Provide the user's credentials to your script, as described in the [boto tutorial](http://boto.cloudhackers.com/en/latest/boto_config_tut.html).
The easiest thing to do is to specify the credentials as environment variables, e.g.

```bash
AWS_ACCESS_KEY_ID=AAAA AWS_SECRET_ACCESS_KEY=BBB BUCKET="my_private_s3_bucket" python upload_all_models.py
```

Alternatively, put the credentials in `~/.aws/credentials` or `~/.boto`.