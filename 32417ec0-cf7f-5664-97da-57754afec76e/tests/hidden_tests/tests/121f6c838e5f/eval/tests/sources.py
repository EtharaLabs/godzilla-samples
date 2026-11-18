"""Go source fixtures shared by several test modules."""

from conftest import GO_MOD

# A package in which every analyzer rule has something to say.
APP_USER = """package app

type user struct {
	//declscope:private
	name string
}

//declscope:shared
func Helper() {}

//declscope:ignore boundary
func greet(u user) string { return u.name }

func load() int { return 1 }

//declscope:shared
func userShared() {}

var _ = greet
var _ = userShared
"""

APP_ORDER = "package app\n\nfunc orderTotal() int { return load() }\n\nvar _ = orderTotal\n"

# A core namespace, a member crossing and a method crossing.
B_STATEMENT = """//declscope:core

package b

type Statement struct {
	Table  string
	wheres []string
}

func open() {}
"""

B_QUERY = """package b

func (s *Statement) Where(cond string) *Statement {
	s.wheres = append(s.wheres, cond)
	open()
	return s
}

func (s *Statement) helper() {}
"""

B_OTHER = "package b\n\nfunc other(s *Statement) { s.helper() }\n\nvar _ = other\n"

# shrink: Format is exported and used by nothing outside internal/user.
SHRINK_USER = """package user

import "fmt"

func Load(id int) string { return Format(id) }

// Format renders an ID for display.
func Format(id int) string { return fmt.Sprint(id) }
"""

SHRINK_API = 'package api\n\nimport "example.com/app/internal/user"\n\nvar _ = user.Load\n'

BROKEN = 'package broken\n\nfunc F() int { return "x" }\n'
DEPENDS_ON_BROKEN = 'package dep\n\nimport "example.com/app/broken"\n\nvar _ = broken.F\n'
TEST_ONLY = 'package testonly\n\nimport "testing"\n\nfunc TestT(t *testing.T) {}\n'

MODULE = {
    "go.mod": GO_MOD,
    "app/user.go": APP_USER,
    "app/order.go": APP_ORDER,
    "b/statement.go": B_STATEMENT,
    "b/query.go": B_QUERY,
    "b/other.go": B_OTHER,
    "internal/user/user.go": SHRINK_USER,
    "api/api.go": SHRINK_API,
}
