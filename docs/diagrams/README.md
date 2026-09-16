# UML Diagram Sources

Three diagrams, written as PlantUML source and pre-rendered to PNG (both
committed, so nothing needs to be regenerated just to read the docs):

| File | Diagram type | Shows |
|---|---|---|
| `data_model.puml` | UML class diagram (styled as an ER diagram) | All 7 tables, PK/FK stereotypes, relationships with multiplicity |
| `architecture.puml` | UML component diagram | The 6-phase pipeline, data flow between stages |
| `pipeline_sequence.puml` | UML sequence diagram | Full execution order across a real pipeline run, including each stage's internal validation call |

## Regenerating after an edit

Requires Java and the PlantUML jar (not committed — 22MB, and irrelevant to
anyone not editing diagrams):

```bash
# Download once:
curl -sL -o plantuml.jar \
  "https://github.com/plantuml/plantuml/releases/download/v1.2024.7/plantuml-1.2024.7.jar"

# Render all three to PNG:
java -jar plantuml.jar -tpng docs/diagrams/*.puml
```

No Graphviz dependency for these three diagrams specifically — class,
component, and sequence diagrams use PlantUML's own internal layout engine,
not the `dot` backend.

## Why PlantUML rather than hand-drawn diagrams

The diagrams are generated from plain-text source under version control,
so they update as fast as editing a text file, diff cleanly in pull
requests, and can't silently drift out of sync with a hand-maintained image
the way a screenshot or a PowerPoint export would.
