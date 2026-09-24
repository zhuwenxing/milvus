//go:build e2e_coverage

package initcore

/*
#cgo pkg-config: milvus_core
#cgo CFLAGS: -DMILVUS_E2E_COVERAGE
#include "common/init_c.h"
*/
import "C"

func DumpMilvusCoreCoverage() {
	C.DumpMilvusCoreCoverage()
}

func ResetMilvusCoreCoverage() {
	C.ResetMilvusCoreCoverage()
}
