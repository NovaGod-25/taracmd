#!/usr/bin/env perl
# Tiny static server for web/, so the page runs on a real http origin.
#
# Needed because a file:// (or data:) page gets an opaque origin and
# localStorage is disabled there — which is the same reason the Android build
# serves itself over https://appassets.androidplatform.net/ instead of
# file:///android_asset/. Testing the revision ticks needs a real origin.
#
# usage: perl tools/serve.pl [port]
use strict;
use warnings;
use HTTP::Daemon;
use HTTP::Status;

$| = 1;                                        # log as it happens, not at exit

my $port = shift || 8787;
my $root = 'web';
die "run me from the repo root (no $root/ here)\n" unless -d $root;

my $d = HTTP::Daemon->new(LocalAddr => '127.0.0.1', LocalPort => $port, ReuseAddr => 1)
    or die "cannot listen on $port: $!\n";

my %TYPE = (
    html => 'text/html; charset=utf-8',
    js   => 'application/javascript; charset=utf-8',
    svg  => 'image/svg+xml',
    json => 'application/json; charset=utf-8',
    webmanifest => 'application/manifest+json; charset=utf-8',
);

print "serving $root/ at ", $d->url, "taracmd.html\n";

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
