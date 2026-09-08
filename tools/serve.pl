#!/usr/bin/env perl
# Tiny static server for web/, so the page runs on a real http origin.
#
# Needed because a file:// (or data:) page gets an opaque origin and
# localStorage is disabled there — which is the same reason the Android build
# serves itself over https://appassets.androidplatform.net/ instead of
# file:///android_asset/. Testing the revision ticks needs a real origin.
#
# usage: perl tools/serve.pl [port] [--lan]
use strict;
use warnings;
use HTTP::Daemon;
use HTTP::Status;

$| = 1;                                        # log as it happens, not at exit

# --lan binds every interface instead of loopback, so a phone on the same
# Wi-Fi can open the page. That is the case worth having: this is a phone app,
# and judging it on the machine that built it tells you least about it. Opt-in,
# because it does put web/ on the local network for as long as the server runs.
my $lan = 0;
my @args;
for (@ARGV) { $_ eq '--lan' ? ($lan = 1) : push @args, $_ }

my $port = $args[0] || 8787;
my $root = 'web';
die "run me from the repo root (no $root/ here)\n" unless -d $root;

my $d = HTTP::Daemon->new(
    LocalAddr => $lan ? '0.0.0.0' : '127.0.0.1',
    LocalPort => $port, ReuseAddr => 1)
    or die "cannot listen on $port: $!\n";

my %TYPE = (
    html => 'text/html; charset=utf-8',
    js   => 'application/javascript; charset=utf-8',
    svg  => 'image/svg+xml',
    json => 'application/json; charset=utf-8',
    webmanifest => 'application/manifest+json; charset=utf-8',
);

print "serving $root/ at http://127.0.0.1:$port/taracmd.html\n";
if ($lan) {
    # Print the addresses this machine actually answers on, so the URL can be
    # typed into a phone rather than worked out.
    my $out = `ipconfig 2>nul` || `ip -4 addr 2>/dev/null` || '';
    my @ips;
    # Only this machine's own addresses. Scanning every dotted quad in
    # ipconfig also picks up the default gateway and the subnet mask, and a
    # gateway printed as "open this on your phone" is a URL that will not load.
    while ($out =~ /^\s*(?:IPv4 Address[^:]*|inet)\s*[.: ]\s*(\d+\.\d+\.\d+\.\d+)/gm) {
        my $ip = $1;
        next if $ip =~ /^(127\.|0\.|255\.)/ || $ip =~ /\.255$/;
        push @ips, $ip unless grep { $_ eq $ip } @ips;
    }
    print "  from the phone:  http://$_:$port/taracmd.html\n" for @ips;
    print "  same Wi-Fi, and Ctrl-C here takes it down again\n";
}

while (my $c = $d->accept) {
    # One request per connection, then close.
    #
    # Keep-alive would be nicer, but this loop is single-threaded: holding a
    # connection open to wait for a second request blocks accept(), and the
    # browser fetches the service-worker script on its own connection. That
    # deadlocks registration with a useless "unknown error occurred when
    # fetching the script".
    my $r = $c->get_request;
    if (!$r) { $c->close; next }

    if ($r->method ne 'GET') { $c->send_error(RC_FORBIDDEN); $c->close; next }

    my $path = $r->uri->path;
    $path = '/taracmd.html' if $path eq '/';
    $path =~ s{\.\.}{}g;                       # no climbing out of web/
    my $file = $root . $path;

    unless (-f $file) {
        print "  GET $path -> 404\n";
        $c->send_error(RC_NOT_FOUND); $c->close; next;
    }

    my ($ext) = $file =~ /\.([a-z]+)$/i;
    my $res = HTTP::Response->new(RC_OK);
    $res->header('Content-Type' => $TYPE{lc($ext // '')} // 'application/octet-stream');
    $res->header('Cache-Control' => 'no-store');
    $res->header('Connection' => 'close');
    open(my $fh, '<:raw', $file) or do {
        $c->send_error(RC_INTERNAL_SERVER_ERROR); $c->close; next;
    };
    { local $/; $res->content(<$fh>); }
    close $fh;
    $c->send_response($res);
    $c->close;

    print "  GET $path -> ", length($res->content), " B\n";
}
