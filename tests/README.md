# Unit Tests

Testing covers userpersistence functions for extracting and transmitting user variables and definitions, and kernel functionality.

In kernel test, we spawn a kernel instance which executes given cells and returns an output verified against the ground truth. For the testing suite, cells are represented by a list of tuples, each tuple containing code block string and respective output; output itself is a list of strings, since cell might call `send_response()` multiple times (e.g. subprocess output is printed in chunks). Data is stored in YAML files.

Notebook:
```
code_block_1
----
output_1_1
```

```
code_block_2
----
output_2_1
output_2_2
```

Python:
```
[(code_block_1, [output_1_1]),
 (code_block_1, [output_2_1, output_2_2])
]
```

YAML:

```
-
  - |-
  code_block_1
  - - output_1_1
-
  - |-
  code_block_2
  - - output_2_1
  - - output_2_2
```