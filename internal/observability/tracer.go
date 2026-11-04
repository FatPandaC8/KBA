package observability

import (
	"context"
	"os"

	"go.opentelemetry.io/otel"
	"go.opentelemetry.io/otel/propagation"
	sdktrace "go.opentelemetry.io/otel/sdk/trace"
	"go.opentelemetry.io/otel/trace"
	"go.opentelemetry.io/otel/trace/noop"
)

var globalTracer trace.Tracer

// InitTracer initializes OpenTelemetry tracing.
// On Android Termux, if OTEL_ENABLED is not set to "true", a lightweight NoopTracer is configured,
// ensuring zero background CPU, zero memory overhead, and zero network traffic.
func InitTracer(serviceName, env string) (trace.Tracer, func(context.Context) error, error) {
	otel.SetTextMapPropagator(propagation.NewCompositeTextMapPropagator(
		propagation.TraceContext{},
		propagation.Baggage{},
	))

	if os.Getenv("OTEL_ENABLED") != "true" {
		// Use standard OpenTelemetry no-op tracer
		provider := noop.NewTracerProvider()
		otel.SetTracerProvider(provider)
		globalTracer = provider.Tracer(serviceName)
		return globalTracer, func(ctx context.Context) error { return nil }, nil
	}

	// When enabled, create standard TracerProvider (supports stdout or custom exporter)
	tp := sdktrace.NewTracerProvider(
		sdktrace.WithSampler(sdktrace.ParentBased(sdktrace.TraceIDRatioBased(0.1))),
	)
	otel.SetTracerProvider(tp)
	globalTracer = tp.Tracer(serviceName)

	cleanup := func(ctx context.Context) error {
		return tp.Shutdown(ctx)
	}

	return globalTracer, cleanup, nil
}

// GetTracer returns the package tracer instance
func GetTracer() trace.Tracer {
	if globalTracer == nil {
		globalTracer = otel.GetTracerProvider().Tracer("gusby")
	}
	return globalTracer
}

// StartSpan is a convenience helper to start a new tracing span
func StartSpan(ctx context.Context, spanName string, opts ...trace.SpanStartOption) (context.Context, trace.Span) {
	return GetTracer().Start(ctx, spanName, opts...)
}
