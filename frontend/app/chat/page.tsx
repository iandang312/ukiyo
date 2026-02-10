import { Button } from "@/components/ui/button";
import Link from "next/dist/client/link";

export default function SignUpPage() {
    return (
        <div>
            <section className="min-h-screen bg-white flex items-center justify-center">
                <div className="max-w-4xl px-6 text-center">
                <h2 className="text-4xl text-black mb-4">
                    i havent set this up yet
                </h2>
                <h3 className="text-lg text-gray-600">
                    isnt this pretty cool though?
                </h3>
                <h5 className="text-lg text-gray-600">
                    why did u say no...
                </h5>
                </div>

            <div style={{ position: "absolute", bottom: "10%", width: "100%", display: "flex", justifyContent: "center" }}>
                <Button variant="ghost" className="rounded-full bg-black text-white hover:bg-gray-300 ">
                    <Link href="/">back to home</Link>
                </Button>
            </div>
            </section>
        </div>
    );
}