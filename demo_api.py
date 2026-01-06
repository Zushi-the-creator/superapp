#!/usr/bin/env python3
"""
Simple HTTP API Demo (without FastAPI)
Demonstrates the REST endpoints
"""

from http.server import HTTPServer, BaseHTTPRequestHandler
import json
from urllib.parse import urlparse, parse_qs
from demo_scanner import SimplifiedScanner

# Global scanner instance
scanner = SimplifiedScanner()
scan_results = []


class APIHandler(BaseHTTPRequestHandler):
    """Simple HTTP request handler"""

    def _set_headers(self, status=200):
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()

    def do_GET(self):
        """Handle GET requests"""
        parsed_path = urlparse(self.path)
        path = parsed_path.path
        query_params = parse_qs(parsed_path.query)

        # Root endpoint
        if path == '/':
            self._set_headers()
            response = {
                "status": "online",
                "app": "NASDAQ Super App Demo",
                "version": "1.0.0",
                "endpoints": {
                    "scanner_stats": "/api/scanner/stats",
                    "top_signals": "/api/stocks/top-signals?signal_type=BUY&limit=5",
                    "stock_detail": "/api/stocks/{ticker}",
                    "scan_now": "/api/scanner/scan-now"
                }
            }
            self.wfile.write(json.dumps(response, indent=2).encode())

        # Scanner stats
        elif path == '/api/scanner/stats':
            self._set_headers()
            response = {
                "total_tickers": len(scanner.tickers),
                "scanned_tickers": len(scan_results),
                "hot_tickers": len([s for s in scan_results if s.get('is_hot')]),
                "last_scan": scan_results[0]['last_updated'] if scan_results else None
            }
            self.wfile.write(json.dumps(response, indent=2).encode())

        # Top signals
        elif path == '/api/stocks/top-signals':
            global scan_results
            signal_type = query_params.get('signal_type', [None])[0]
            limit = int(query_params.get('limit', [10])[0])

            if not scan_results:
                scan_results = scanner.scan_all()

            top_signals = scanner.get_top_signals(scan_results, signal_type, limit)

            self._set_headers()
            response = {
                "count": len(top_signals),
                "signal_type": signal_type,
                "stocks": top_signals
            }
            self.wfile.write(json.dumps(response, indent=2).encode())

        # Stock detail
        elif path.startswith('/api/stocks/'):
            global scan_results
            ticker = path.split('/')[-1].upper()

            if not scan_results:
                scan_results = scanner.scan_all()

            stock = next((s for s in scan_results if s['ticker'] == ticker), None)

            if stock:
                self._set_headers()
                self.wfile.write(json.dumps(stock, indent=2).encode())
            else:
                self._set_headers(404)
                self.wfile.write(json.dumps({
                    "error": f"Stock {ticker} not found"
                }).encode())

        # Scan now
        elif path == '/api/scanner/scan-now':
            global scan_results
            scan_results = scanner.scan_all()

            self._set_headers()
            response = {
                "status": "scan_complete",
                "scanned": len(scan_results),
                "timestamp": scan_results[0]['last_updated'] if scan_results else None
            }
            self.wfile.write(json.dumps(response, indent=2).encode())

        else:
            self._set_headers(404)
            self.wfile.write(json.dumps({"error": "Not found"}).encode())

    def log_message(self, format, *args):
        """Custom log message"""
        print(f"[API] {self.address_string()} - {format % args}")


def run_server(port=8000):
    """Run the demo API server"""
    server_address = ('', port)
    httpd = HTTPServer(server_address, APIHandler)

    print(f"""
╔══════════════════════════════════════════════════════════════╗
║         🚀 NASDAQ SUPER APP - DEMO API SERVER                ║
╠══════════════════════════════════════════════════════════════╣
║  Status: Running                                             ║
║  Port: {port}                                                    ║
║  URL: http://localhost:{port}                                    ║
╠══════════════════════════════════════════════════════════════╣
║  📍 Available Endpoints:                                     ║
║                                                              ║
║  GET  /                                                      ║
║       → API info and endpoints                              ║
║                                                              ║
║  GET  /api/scanner/stats                                     ║
║       → Scanner statistics                                   ║
║                                                              ║
║  GET  /api/stocks/top-signals?signal_type=BUY&limit=5       ║
║       → Top buy/sell signals                                ║
║                                                              ║
║  GET  /api/stocks/AAPL                                       ║
║       → Detailed stock data                                  ║
║                                                              ║
║  GET  /api/scanner/scan-now                                  ║
║       → Trigger immediate scan                               ║
╠══════════════════════════════════════════════════════════════╣
║  🧪 Test Commands:                                           ║
║                                                              ║
║  curl http://localhost:{port}/api/scanner/stats                  ║
║  curl http://localhost:{port}/api/stocks/top-signals?signal_type=BUY ║
║  curl http://localhost:{port}/api/stocks/NVDA                    ║
╠══════════════════════════════════════════════════════════════╣
║  Press Ctrl+C to stop                                        ║
╚══════════════════════════════════════════════════════════════╝
    """)

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n\n🛑 Server stopped")
        httpd.server_close()


if __name__ == '__main__':
    # Perform initial scan
    print("\n📊 Performing initial scan...")
    scan_results = scanner.scan_all()
    print(f"✅ Scanned {len(scan_results)} stocks\n")

    # Start server
    run_server(8000)
