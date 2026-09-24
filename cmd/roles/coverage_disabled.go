//go:build !e2e_coverage

package roles

func startCoverageSignalHandler() func() {
	return func() {}
}
