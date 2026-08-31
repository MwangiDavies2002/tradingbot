import React from 'react';

export interface Candle {
  ts: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume?: number;
}

interface CandlestickChartProps {
  candles: Candle[];
  width?: number;
  height?: number;
  showVolume?: boolean;
}

export const CandlestickChart: React.FC<CandlestickChartProps> = ({
  candles,
  width = 800,
  height = 300,
  showVolume = false,
}) => {
  if (!candles || candles.length === 0) {
    return (
      <div className="flex items-center justify-center p-8 text-slate-500">
        No candle data available
      </div>
    );
  }

  const chartHeight = showVolume ? height * 0.7 : height;
  const volumeHeight = height * 0.3;
  const padding = 40;
  const chartWidth = width - padding * 2;
  const candleWidth = Math.max(2, Math.min(8, chartWidth / candles.length));
  const spaceBetween = chartWidth / candles.length;

  // Find min/max for scaling
  const allPrices = candles.flatMap(c => [c.high, c.low]);
  const minPrice = Math.min(...allPrices);
  const maxPrice = Math.max(...allPrices);
  const priceRange = maxPrice - minPrice || 1;
  const padding_price = priceRange * 0.05;

  const scaleY = (price: number) => {
    const normalized = (price - minPrice + padding_price) / (priceRange + padding_price * 2);
    return chartHeight - normalized * chartHeight;
  };

  const renderCandle = (candle: Candle, index: number) => {
    const x = padding + index * spaceBetween + spaceBetween / 2;
    const highY = scaleY(candle.high);
    const lowY = scaleY(candle.low);
    const openY = scaleY(candle.open);
    const closeY = scaleY(candle.close);

    const isGreen = candle.close >= candle.open;
    const bodyTop = Math.min(openY, closeY);
    const bodyBottom = Math.max(openY, closeY);
    const bodyHeight = Math.max(bodyBottom - bodyTop, 1);

    const color = isGreen ? '#10b981' : '#ef4444';
    const bodyColor = isGreen ? '#6ee7b7' : '#fca5a5';

    return (
      <g key={index}>
        {/* Wick (high-low line) */}
        <line
          x1={x}
          y1={highY}
          x2={x}
          y2={lowY}
          stroke={color}
          strokeWidth="0.5"
          opacity="0.6"
        />
        {/* Body (open-close box) */}
        <rect
          x={x - candleWidth / 2}
          y={bodyTop}
          width={candleWidth}
          height={bodyHeight}
          fill={bodyColor}
          stroke={color}
          strokeWidth="1"
        />
      </g>
    );
  };

  return (
    <div className="w-full">
      <svg width={width} height={height} className="border border-slate-600 rounded bg-slate-900">
        <defs>
          <pattern id="grid" width="50" height="50" patternUnits="userSpaceOnUse">
            <path
              d="M 50 0 L 0 0 0 50"
              fill="none"
              stroke="#334155"
              strokeWidth="0.5"
            />
          </pattern>
        </defs>

        {/* Grid background */}
        <rect width={width} height={height} fill="url(#grid)" />

        {/* Y-axis labels */}
        <text x={10} y={20} fontSize="10" fill="#94a3b8" textAnchor="end">
          {(maxPrice + padding_price).toFixed(2)}
        </text>
        <text x={10} y={chartHeight - 10} fontSize="10" fill="#94a3b8" textAnchor="end">
          {(minPrice - padding_price).toFixed(2)}
        </text>

        {/* Candles group */}
        <g clipPath={`url(#clip${width})`}>
          {candles.map((candle, index) => renderCandle(candle, index))}
        </g>

        {/* Clip path for candles area */}
        <defs>
          <clipPath id={`clip${width}`}>
            <rect x={padding} y={0} width={chartWidth} height={chartHeight} />
          </clipPath>
        </defs>

        {/* Axes */}
        <line x1={padding} y1={0} x2={padding} y2={height} stroke="#64748b" strokeWidth="1" />
        <line x1={padding} y1={chartHeight} x2={width} y2={chartHeight} stroke="#64748b" strokeWidth="1" />
      </svg>

      <div className="mt-2 text-xs text-slate-500 text-center">
        {candles.length} candles • Price range: {minPrice.toFixed(2)} - {maxPrice.toFixed(2)}
      </div>
    </div>
  );
};
