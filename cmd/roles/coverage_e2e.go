//go:build e2e_coverage

package roles

import (
	"context"
	"os"
	"os/signal"
	"path/filepath"
	"runtime/coverage"
	"strconv"
	"syscall"
	"time"

	"github.com/milvus-io/milvus/internal/util/initcore"
	"github.com/milvus-io/milvus/pkg/v3/mlog"
)

const coverageRoot = "/tmp/milvus-e2e-coverage"

func startCoverageSignalHandler() func() {
	signals := make(chan os.Signal, 1)
	done := make(chan struct{})
	signal.Notify(signals, syscall.SIGUSR1, syscall.SIGUSR2)
	go func() {
		for {
			select {
			case sig := <-signals:
				switch sig {
				case syscall.SIGUSR1:
					writeServerCoverage()
				case syscall.SIGUSR2:
					resetServerCoverage()
				}
			case <-done:
				return
			}
		}
	}()
	return func() {
		signal.Stop(signals)
		close(done)
	}
}

func writeServerCoverage() {
	ctx := context.TODO()
	goDir := filepath.Join(coverageRoot, "go")
	cppDir := filepath.Join(coverageRoot, "cpp")
	for _, dir := range []string{goDir, cppDir} {
		if err := os.MkdirAll(dir, 0o755); err != nil {
			mlog.Error(ctx, "create coverage directory failed", mlog.String("directory", dir), mlog.Err(err))
			return
		}
	}
	if err := coverage.WriteMetaDir(goDir); err != nil {
		mlog.Error(ctx, "write Go coverage metadata failed", mlog.Err(err))
		return
	}
	if err := coverage.WriteCountersDir(goDir); err != nil {
		mlog.Error(ctx, "write Go coverage counters failed", mlog.Err(err))
		return
	}
	initcore.DumpMilvusCoreCoverage()
	if err := writeCoverageMarker("snapshot.done"); err != nil {
		mlog.Error(ctx, "write server coverage snapshot marker failed", mlog.Err(err))
		return
	}
	mlog.Info(ctx, "server coverage snapshot written", mlog.String("directory", coverageRoot))
}

func resetServerCoverage() {
	ctx := context.TODO()
	if err := coverage.ClearCounters(); err != nil {
		mlog.Error(ctx, "reset Go coverage counters failed", mlog.Err(err))
		return
	}
	initcore.ResetMilvusCoreCoverage()
	if err := writeCoverageMarker("reset.done"); err != nil {
		mlog.Error(ctx, "write server coverage reset marker failed", mlog.Err(err))
		return
	}
	mlog.Info(ctx, "server coverage counters reset")
}

func writeCoverageMarker(name string) error {
	if err := os.MkdirAll(coverageRoot, 0o755); err != nil {
		return err
	}
	path := filepath.Join(coverageRoot, name)
	temporaryPath := path + ".tmp"
	if err := os.WriteFile(temporaryPath, []byte(strconv.FormatInt(time.Now().UnixNano(), 10)), 0o644); err != nil {
		return err
	}
	return os.Rename(temporaryPath, path)
}
