AI job examples
===============
Run one from the AI Jobs app ("Run job file…"), or from a terminal:

    sourabh-ai run ~/SourabhHome/AIJobs/examples/summarise-docs.job.json

To use your own data, copy a .job.json, point "inputs" at your files and edit the prompt.

inputs.type   what each item is                     extra keys
-----------   -----------------------------------   ---------------------------------
folder        one file                              path, glob ("*.txt"), recursive
lines         one non-empty line of a text file     path
csv           one row                               path, column, id_column
list          one string from "items"               items: [...]

Prompt placeholders: {input} {name} {index}, and for CSV every column ({customer} …).
Model: "ollama/<local model>", "anthropic/claude-haiku-5-5", "openai/<model>".
Results: AIJobs/runs/<job>/outputs/*, results.jsonl, results.csv
