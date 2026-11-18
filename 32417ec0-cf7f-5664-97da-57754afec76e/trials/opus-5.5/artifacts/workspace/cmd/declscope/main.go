// Command declscope enforces private and shared pseudo scopes for
// package-level declarations, methods and struct fields.
package main

import (
	"os"

	"declscope/internal/analyzer"
	"declscope/internal/checker"
	"declscope/internal/skill"
)

func main() {
	if len(os.Args) > 1 {
		switch os.Args[1] {
		case "skill":
			os.Exit(skill.Main(os.Args[2:]))
		case "survey":
			os.Exit(analyzer.SurveyMain(os.Args[2:]))
		case "inspect":
			os.Exit(analyzer.InspectMain(os.Args[2:]))
		case "shrink":
			os.Exit(analyzer.ShrinkMain(os.Args[2:]))
		case "baseline":
			os.Exit(analyzer.BaselineMain(os.Args[2:]))
		}
	}
	checker.Main(analyzer.New())
}
